"""
Event CRUD (venue-admin side) plus the public listing used by the venue hub
and venue-scene screens. Access-mode evaluation itself lives in
access_service.py -- this module only manages Event rows.
"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.models import Event, VenueMode, _utcnow
from backend.app.schemas import EventCreate, EventUpdate


async def list_events(db: AsyncSession, venue_id: int, public_only: bool = False) -> List[Event]:
    stmt = select(Event).where(Event.venue_id == venue_id).order_by(Event.start_at.desc())
    if public_only:
        stmt = stmt.where(Event.public_visibility.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def get_event(db: AsyncSession, venue_id: int, event_id: int) -> Optional[Event]:
    result = await db.execute(select(Event).where(Event.id == event_id, Event.venue_id == venue_id))
    return result.scalars().first()


async def create_event(db: AsyncSession, venue_id: int, req: EventCreate) -> Event:
    access_mode = VenueMode(req.access_mode) if req.access_mode else None
    event = Event(
        venue_id=venue_id,
        title=req.title.strip(),
        type=req.type.strip() or "club_night",
        start_at=req.start_at or _utcnow(),
        end_at=req.end_at,
        organizer_name=req.organizer_name,
        access_mode=access_mode,
        observer_mode=req.observer_mode,
        request_access_allowed=req.request_access_allowed,
        guest_capacity=req.guest_capacity,
        public_visibility=req.public_visibility,
    )
    if req.scene_props:
        event.scene_props = req.scene_props
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def update_event(db: AsyncSession, venue_id: int, event_id: int, req: EventUpdate) -> Optional[Event]:
    event = await get_event(db, venue_id, event_id)
    if not event:
        return None
    if req.title is not None:
        event.title = req.title.strip()
    if req.type is not None:
        event.type = req.type.strip() or event.type
    if req.start_at is not None:
        event.start_at = req.start_at
    if req.end_at is not None:
        event.end_at = req.end_at
    if req.organizer_name is not None:
        event.organizer_name = req.organizer_name
    if req.access_mode is not None:
        event.access_mode = VenueMode(req.access_mode) if req.access_mode else None
    if req.observer_mode is not None:
        event.observer_mode = req.observer_mode
    if req.request_access_allowed is not None:
        event.request_access_allowed = req.request_access_allowed
    if req.guest_capacity is not None:
        event.guest_capacity = req.guest_capacity
    if req.scene_props is not None:
        event.scene_props = req.scene_props
    if req.public_visibility is not None:
        event.public_visibility = req.public_visibility
    await db.commit()
    await db.refresh(event)
    return event


async def delete_event(db: AsyncSession, venue_id: int, event_id: int) -> bool:
    event = await get_event(db, venue_id, event_id)
    if not event:
        return False
    await db.delete(event)
    await db.commit()
    return True
