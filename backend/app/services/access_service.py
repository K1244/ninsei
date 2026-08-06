"""
Access Engine -- the single place that decides "can this patron do X at this
venue right now" (PLAN.md section 5). Read-only/side-effect-free: callers
(guest_router.py, ws_router.py, the QR scanner endpoint) use it to decide
what to show or allow, never to mutate anything themselves.

Priority order, per the plan:
  1. Is the venue open at all? (mode == CLOSED short-circuits everything)
  2. Is there an active Event? -- if so, its access_mode (when set) overrides
     the venue's own `mode` for the duration of the event.
  3/4. Does the patron have an explicit, event-scoped entitlement (an
     approved AccessRequest, or a completed one-time-entry Purchase) --
     checked before membership specifically so a private event is never
     silently unlocked by an unrelated general membership (explicit rule
     from the plan).
  5. A membership only grants entry for the venue's general MEMBERS_ONLY
     mode, never for a private/invite-only event.
  6. Otherwise: offer observing and/or requesting access instead of a flat
     deny.

Buying a product or joining a membership never requires already being
"inside" -- those stay available even when entry itself doesn't.

Note on QrPass: it's a digital *ID badge* (get_or_create_pass mints one for
any identified patron, unconditionally -- see qr_service.py), never an
entitlement in its own right. It deliberately does not appear anywhere in
the ladder above: holding one must never grant entry by itself, or anyone
could self-issue a standing bypass into a members-only/private venue with
zero real entitlement behind it. Its only job is as the scanner's lookup key
-- scan_qr_pass below re-runs this same evaluate_access() at scan time for
whoever the badge belongs to, so the door sees their *current* real status
(including a pending AccessRequest, hence "yellow"), not a snapshot from
whenever the badge was issued.
"""
from dataclasses import dataclass
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.models import (
    Venue, VenueMode, Event, User, Membership, AccessRequest, AccessRequestStatus,
    QrPass, QrPassStatus, Purchase, _utcnow,
)


@dataclass
class AccessContext:
    venue: Venue
    active_event: Optional[Event]
    can_view_venue: bool = False
    can_enter_venue: bool = False
    can_observe_event: bool = False
    can_request_access: bool = False
    can_use_jukebox: bool = False
    can_show_qr: bool = False
    can_buy_product: bool = False
    can_join_membership: bool = False
    reason: str = ""


async def get_active_event(db: AsyncSession, venue_id: int) -> Optional[Event]:
    """The currently-active event for this venue, if any. If more than one
    happens to overlap (an owner scheduling mistake -- there's no conflict
    validation yet), the most recently started one wins; good enough for
    MVP."""
    result = await db.execute(
        select(Event).where(Event.venue_id == venue_id).order_by(Event.start_at.desc())
    )
    for event in result.scalars().all():
        if event.is_active:
            return event
    return None


def _effective_mode(venue: Venue, active_event: Optional[Event]) -> VenueMode:
    if active_event and active_event.access_mode:
        return active_event.access_mode
    return venue.mode


async def _has_event_entitlement(
    db: AsyncSession, user_id: int, venue_id: int, event_id: Optional[int]
) -> bool:
    """An approved AccessRequest, or a completed one_time_entry Purchase,
    scoped to this exact event (or to the venue in general when there's no
    active event)."""
    ar_stmt = select(AccessRequest.id).where(
        AccessRequest.user_id == user_id,
        AccessRequest.venue_id == venue_id,
        AccessRequest.status == AccessRequestStatus.APPROVED,
        AccessRequest.event_id == event_id if event_id else AccessRequest.event_id.is_(None),
    )
    if (await db.execute(ar_stmt)).scalars().first():
        return True

    p_stmt = select(Purchase.id).where(
        Purchase.user_id == user_id,
        Purchase.venue_id == venue_id,
        Purchase.kind == "one_time_entry",
        Purchase.event_id == event_id if event_id else Purchase.event_id.is_(None),
    )
    return (await db.execute(p_stmt)).scalars().first() is not None


async def _has_membership_entitlement(db: AsyncSession, user_id: int, venue_id: int) -> bool:
    result = await db.execute(
        select(Membership).where(Membership.user_id == user_id, Membership.venue_id == venue_id)
    )
    return any(m.is_active for m in result.scalars().all())


async def evaluate_access(db: AsyncSession, venue: Venue, user: Optional[User]) -> AccessContext:
    active_event = await get_active_event(db, venue.id)
    mode = _effective_mode(venue, active_event)
    ctx = AccessContext(venue=venue, active_event=active_event)
    ctx.can_view_venue = True

    if mode == VenueMode.CLOSED:
        ctx.reason = "Venue is closed right now."
        return ctx

    # Available regardless of entry status -- buying merch/a donation/a
    # membership from outside is always allowed while the venue isn't closed,
    # and so is holding/showing your QR badge (see this module's docstring
    # for why a QrPass is an ID badge, not an entitlement -- it deliberately
    # plays no part in the `entered` ladder below).
    ctx.can_buy_product = True
    ctx.can_join_membership = True
    ctx.can_show_qr = user is not None

    entered = False
    if mode == VenueMode.PUBLIC:
        entered = True
        ctx.reason = "Open to everyone."
    elif user is not None:
        event_id = active_event.id if active_event else None
        if await _has_event_entitlement(db, user.id, venue.id, event_id):
            entered = True
            ctx.reason = "Approved access."
        elif mode == VenueMode.MEMBERS_ONLY and await _has_membership_entitlement(db, user.id, venue.id):
            entered = True
            ctx.reason = "Valid membership."

    if entered:
        ctx.can_enter_venue = True
        ctx.can_use_jukebox = True
        return ctx

    # Couldn't enter -- offer the next best thing instead of a flat deny.
    ctx.can_observe_event = mode == VenueMode.OBSERVER_ALLOWED or bool(active_event and active_event.observer_mode)
    ctx.can_request_access = bool(active_event.request_access_allowed) if active_event else True

    if user is None:
        ctx.reason = "Identify yourself to request access." if not ctx.can_observe_event else \
            "Observer mode only -- identify yourself to request access."
    elif ctx.can_observe_event:
        ctx.reason = "You can watch as an observer, or request access."
    elif ctx.can_request_access:
        ctx.reason = "Request access from the organizer."
    else:
        ctx.reason = "This venue/event is closed to you right now."

    return ctx


async def scan_qr_pass(db: AsyncSession, venue: Venue, token: str) -> dict:
    """Staff scanner flow (PLAN.md section 8): looks up the QR pass, re-runs
    the same access engine the pass holder would see, and returns a
    green/yellow/red-style verdict. Never trusts anything encoded in the QR
    itself beyond the opaque token -- all state lives server-side."""
    result = await db.execute(
        select(QrPass).where(QrPass.token == token, QrPass.venue_id == venue.id)
    )
    qr = result.scalars().first()
    if not qr or qr.status != QrPassStatus.ACTIVE:
        return {"result": "deny", "reason": "Unknown or revoked QR pass.", "user_display_name": None}
    if qr.expires_at and qr.expires_at < _utcnow():
        return {"result": "deny", "reason": "This QR pass has expired.", "user_display_name": None}

    user = (await db.execute(select(User).where(User.id == qr.user_id))).scalars().first()
    if not user:
        return {"result": "deny", "reason": "Pass holder not found.", "user_display_name": None}

    ctx = await evaluate_access(db, venue, user)
    if ctx.can_enter_venue:
        return {"result": "allow", "reason": ctx.reason, "user_display_name": user.display_name}

    event_id = ctx.active_event.id if ctx.active_event else None
    pending_stmt = select(AccessRequest.id).where(
        AccessRequest.user_id == user.id,
        AccessRequest.venue_id == venue.id,
        AccessRequest.status == AccessRequestStatus.PENDING,
        AccessRequest.event_id == event_id if event_id else AccessRequest.event_id.is_(None),
    )
    if (await db.execute(pending_stmt)).scalars().first():
        return {"result": "pending", "reason": "Access request awaiting approval.", "user_display_name": user.display_name}

    return {"result": "deny", "reason": ctx.reason or "No valid access.", "user_display_name": user.display_name}
