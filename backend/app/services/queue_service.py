from typing import List, Optional, Dict, Any, Set
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.app.models import QueueItem, QueueStatus
from backend.app.schemas import QueueAddRequest
from backend.app.services.ws_manager import ws_manager

async def get_current_queue_models(db: AsyncSession, venue_id: int) -> List[QueueItem]:
    # Query playing track first, followed by queued tracks sorted by priority_score DESC, created_at ASC
    result = await db.execute(
        select(QueueItem)
        .where(
            QueueItem.venue_id == venue_id,
            QueueItem.status.in_([QueueStatus.PLAYING, QueueStatus.QUEUED]),
        )
        .order_by(
            QueueItem.status != QueueStatus.PLAYING, # PLAYING comes first
            QueueItem.priority_score.desc(),
            QueueItem.created_at.asc()
        )
    )
    return result.scalars().all()

async def get_current_queue_response(db: AsyncSession, venue_id: int) -> List[Dict[str, Any]]:
    items = await get_current_queue_models(db, venue_id)
    response = []
    for item in items:
        response.append({
            "id": item.id,
            "song_id": item.song_id,
            "title": item.title,
            "artist": item.artist,
            "duration_seconds": item.duration_seconds,
            "thumbnail_url": item.thumbnail_url,
            "provider": item.provider,
            "priority_score": item.priority_score,
            "status": item.status.value,
            "paid_amount": item.paid_amount,
            "style": item.style,
            "is_autofilled": item.is_autofilled,
            "added_by_user": "Guest",
            "created_at": item.created_at.isoformat()
        })
    return response

async def get_currently_playing_track(db: AsyncSession, venue_id: int) -> Optional[QueueItem]:
    result = await db.execute(
        select(QueueItem).where(QueueItem.venue_id == venue_id, QueueItem.status == QueueStatus.PLAYING)
    )
    return result.scalars().first()

async def get_queue_item(db: AsyncSession, venue_id: int, queue_id: int) -> Optional[QueueItem]:
    """Tenant-scoped lookup -- always filter by venue_id alongside the id, so
    one venue can never read/mutate another venue's queue item by guessing IDs."""
    result = await db.execute(
        select(QueueItem).where(QueueItem.id == queue_id, QueueItem.venue_id == venue_id)
    )
    return result.scalars().first()

async def broadcast_queue_state(db: AsyncSession, venue_id: int):
    queue = await get_current_queue_response(db, venue_id)
    currently_playing = next((item for item in queue if item["status"] == "playing"), None)

    await ws_manager.broadcast(venue_id, "QUEUE_UPDATED", {
        "queue": queue,
        "currently_playing": currently_playing
    })

async def _insert_queue_item(
    db: AsyncSession,
    venue_id: int,
    req: QueueAddRequest,
    style: Optional[str] = None,
    is_autofilled: bool = False,
) -> QueueItem:
    """Shared insertion path for a guest's free add, a premium-style-unlock
    add (payment_service.unlock_premium_style_and_add), and the autoplay
    filler (autoplay_service.maybe_fill_queue). Commits, broadcasts the
    updated queue, and dispatches PLAY_TRACK if this item starts playing
    immediately -- callers don't need to repeat any of that."""
    # Check if there is an active playing track
    playing_track = await get_currently_playing_track(db, venue_id)

    # Initial status: if nothing is playing, make this track PLAYING immediately; otherwise QUEUED
    initial_status = QueueStatus.PLAYING if not playing_track else QueueStatus.QUEUED

    # Base priority score is 0.0
    queue_item = QueueItem(
        venue_id=venue_id,
        song_id=req.song_id,
        title=req.title,
        artist=req.artist,
        duration_seconds=req.duration_seconds,
        thumbnail_url=req.thumbnail_url,
        provider=req.provider,
        style=style,
        is_autofilled=is_autofilled,
        priority_score=0.0,
        status=initial_status,
        paid_amount=0.0
    )

    db.add(queue_item)
    await db.commit()
    await db.refresh(queue_item)

    # Broadcast updated queue to all connected clients of this venue
    await broadcast_queue_state(db, venue_id)

    # If this new song is set to PLAYING, instruct playback client to play it
    if initial_status == QueueStatus.PLAYING:
        await ws_manager.broadcast(venue_id, "PLAY_TRACK", {
            "queue_id": queue_item.id,
            "song_id": queue_item.song_id,
            "title": queue_item.title,
            "artist": queue_item.artist,
            "thumbnail_url": queue_item.thumbnail_url,
            "provider": queue_item.provider,
            "duration_seconds": queue_item.duration_seconds
        })

    return queue_item


async def add_track_to_queue(db: AsyncSession, venue_id: int, req: QueueAddRequest) -> Dict[str, Any]:
    queue_item = await _insert_queue_item(db, venue_id, req, style=req.style)
    return {
        "id": queue_item.id,
        "song_id": queue_item.song_id,
        "title": queue_item.title,
        "artist": queue_item.artist,
        "status": queue_item.status.value,
        "message": f"Added '{queue_item.title}' to queue successfully."
    }


async def get_recent_artists(db: AsyncSession, venue_id: int, window: int) -> Set[str]:
    """Artists of the currently-playing track, everything still QUEUED, and
    the most recently COMPLETED/SKIPPED tracks (up to `window` of them) --
    used by the autoplay filler to avoid repeating an artist back-to-back."""
    artists: Set[str] = set()

    active = await db.execute(
        select(QueueItem.artist).where(
            QueueItem.venue_id == venue_id,
            QueueItem.status.in_([QueueStatus.PLAYING, QueueStatus.QUEUED]),
        )
    )
    artists.update(a for a in active.scalars().all() if a)

    recent = await db.execute(
        select(QueueItem.artist)
        .where(
            QueueItem.venue_id == venue_id,
            QueueItem.status.in_([QueueStatus.COMPLETED, QueueStatus.SKIPPED]),
        )
        .order_by(QueueItem.created_at.desc())
        .limit(window)
    )
    artists.update(a for a in recent.scalars().all() if a)

    return artists

async def advance_queue(db: AsyncSession, venue_id: int) -> Optional[Dict[str, Any]]:
    """Advances queue: marks current PLAYING song as COMPLETED, and sets top QUEUED song to PLAYING."""
    # 1. Mark current playing song completed
    playing_track = await get_currently_playing_track(db, venue_id)
    if playing_track:
        playing_track.status = QueueStatus.COMPLETED
        await db.commit()

    # 2. Pick next highest priority queued song
    result = await db.execute(
        select(QueueItem)
        .where(QueueItem.venue_id == venue_id, QueueItem.status == QueueStatus.QUEUED)
        .order_by(QueueItem.priority_score.desc(), QueueItem.created_at.asc())
    )
    next_track = result.scalars().first()

    if next_track:
        next_track.status = QueueStatus.PLAYING
        await db.commit()
        await db.refresh(next_track)

        # Broadcast updated queue state
        await broadcast_queue_state(db, venue_id)

        # Send play command to playback client
        track_payload = {
            "queue_id": next_track.id,
            "song_id": next_track.song_id,
            "title": next_track.title,
            "artist": next_track.artist,
            "thumbnail_url": next_track.thumbnail_url,
            "provider": next_track.provider,
            "duration_seconds": next_track.duration_seconds
        }
        await ws_manager.broadcast(venue_id, "PLAY_TRACK", track_payload)
        return track_payload
    else:
        # No more tracks in queue
        await broadcast_queue_state(db, venue_id)
        await ws_manager.broadcast(venue_id, "PLAY_TRACK", {
            "queue_id": None,
            "song_id": None,
            "message": "Queue is empty."
        })
        return None

async def skip_current_track(db: AsyncSession, venue_id: int):
    playing_track = await get_currently_playing_track(db, venue_id)
    if playing_track:
        playing_track.status = QueueStatus.SKIPPED
        await db.commit()
    return await advance_queue(db, venue_id)

async def remove_from_queue(db: AsyncSession, venue_id: int, queue_id: int):
    item = await get_queue_item(db, venue_id, queue_id)
    if item:
        if item.status == QueueStatus.PLAYING:
            await skip_current_track(db, venue_id)
        else:
            await db.delete(item)
            await db.commit()
            await broadcast_queue_state(db, venue_id)
        return True
    return False

async def clear_queue(db: AsyncSession, venue_id: int):
    items = await get_current_queue_models(db, venue_id)
    for item in items:
        await db.delete(item)
    await db.commit()
    await broadcast_queue_state(db, venue_id)
    await ws_manager.broadcast(venue_id, "PLAY_TRACK", {
        "queue_id": None,
        "song_id": None,
        "message": "Queue cleared."
    })
