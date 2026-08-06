"""
Pro-only "manage the playlist in advance" autoplay filler. When a Pro venue
has autoplay_enabled and real requests run low, top up the queue from that
venue's own request history -- weighted toward preferred styles, excluding
prohibited ones, and never repeating an artist within a short recent window
(settings.AUTOPLAY_NO_REPEAT_ARTIST_WINDOW).

Called from the natural "queue just got shorter" points (a guest adding a
song, a track ending, an owner skipping) -- see guest_router.py, ws_router.py,
venue_router.py. Callers don't await anything from it beyond "did it not
crash"; maybe_fill_queue swallows its own errors so a flaky provider search
never blocks real playback.
"""
import random
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from backend.app.config import settings
from backend.app.models import Venue, QueueItem, QueueStatus, StyleRule
from backend.app.schemas import QueueAddRequest
from backend.app.services import style_service
from backend.app.services.queue_service import _insert_queue_item, get_recent_artists
from backend.app.media_providers.factory import MediaProviderFactory


async def _build_candidate_pool(db: AsyncSession, venue: Venue) -> List[Tuple[QueueItem, int]]:
    """One (representative row, weight) per distinct song_id this venue has
    ever had requested, weight = request frequency (x3 if the song's style
    is 'preferred'), excluding anything tagged with a 'prohibited' style."""
    result = await db.execute(select(QueueItem).where(QueueItem.venue_id == venue.id))
    all_items = result.scalars().all()
    if not all_items:
        return []

    styles = await style_service.list_venue_styles(db, venue.id)
    rule_by_name = {s.name.lower(): s.rule for s in styles}

    freq = {}
    representative = {}
    for item in all_items:
        freq[item.song_id] = freq.get(item.song_id, 0) + 1
        representative[item.song_id] = item  # last write wins; fine, all copies share title/artist/style

    candidates = []
    for song_id, item in representative.items():
        rule = rule_by_name.get((item.style or "").lower())
        if rule == StyleRule.PROHIBITED:
            continue
        weight = freq[song_id] * (3 if rule == StyleRule.PREFERRED else 1)
        candidates.append((item, weight))
    return candidates


async def _fallback_provider_search(db: AsyncSession, venue: Venue, recent_artists: set):
    """No usable history yet (e.g. a brand-new venue) -- best-effort search
    the venue's active provider for something in a preferred style. Any
    failure here is swallowed by the caller; this never blocks playback."""
    try:
        provider = MediaProviderFactory.get_provider(venue.active_provider)
    except ValueError:
        return

    styles = await style_service.list_venue_styles(db, venue.id)
    preferred_names = [s.name for s in styles if s.rule == StyleRule.PREFERRED]
    query = random.choice(preferred_names) if preferred_names else "party hits"

    results = await provider.search_tracks(query, limit=10)
    if not results:
        return

    pick = next((r for r in results if r.artist not in recent_artists), results[0])
    req = QueueAddRequest(
        song_id=pick.song_id,
        title=pick.title,
        artist=pick.artist,
        duration_seconds=pick.duration_seconds,
        thumbnail_url=pick.thumbnail_url,
        provider=pick.provider,
    )
    style_tag = preferred_names[0] if preferred_names and query in preferred_names else None
    await _insert_queue_item(db, venue.id, req, style=style_tag, is_autofilled=True)


async def maybe_fill_queue(db: AsyncSession, venue_id: int) -> None:
    try:
        venue = (await db.execute(select(Venue).where(Venue.id == venue_id))).scalars().first()
        if not venue or venue.subscription_tier != "pro" or not venue.autoplay_enabled:
            return

        queued_count = (await db.execute(
            select(func.count()).select_from(QueueItem).where(
                QueueItem.venue_id == venue_id, QueueItem.status == QueueStatus.QUEUED
            )
        )).scalar()
        if queued_count is not None and queued_count >= settings.AUTOPLAY_FILL_THRESHOLD:
            return

        recent_artists = await get_recent_artists(db, venue_id, settings.AUTOPLAY_NO_REPEAT_ARTIST_WINDOW)
        candidates = await _build_candidate_pool(db, venue)
        filtered = [(item, w) for item, w in candidates if item.artist not in recent_artists]
        # If every candidate collides with the no-repeat window (e.g. a venue
        # with only one artist in its history), relax the constraint rather
        # than leaving the queue empty.
        if not filtered and candidates:
            filtered = candidates

        if filtered:
            items, weights = zip(*filtered)
            chosen = random.choices(items, weights=weights, k=1)[0]
            req = QueueAddRequest(
                song_id=chosen.song_id,
                title=chosen.title,
                artist=chosen.artist,
                duration_seconds=chosen.duration_seconds,
                thumbnail_url=chosen.thumbnail_url or "",
                provider=chosen.provider,
            )
            await _insert_queue_item(db, venue_id, req, style=chosen.style, is_autofilled=True)
        else:
            await _fallback_provider_search(db, venue, recent_artists)
    except Exception as e:
        # Autoplay is a nice-to-have -- never let it break real requests/playback.
        print(f"[Autoplay] maybe_fill_queue failed for venue {venue_id}: {e}")
