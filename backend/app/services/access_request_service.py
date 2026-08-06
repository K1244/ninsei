"""
AccessRequest CRUD: a patron asking to get into a members-only/private/
invite-only venue or event, and the organizer approving/rejecting it.
Deciding a request doesn't retroactively re-check anything -- the next time
the requester's access is evaluated (access_service.evaluate_access), an
APPROVED request scoped to that venue/event just counts as an entitlement.
"""
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.models import AccessRequest, AccessRequestStatus, User, _utcnow
from backend.app.schemas import AccessRequestCreate


async def create_request(db: AsyncSession, venue_id: int, user: User, req: AccessRequestCreate) -> AccessRequest:
    # Re-requesting while already pending just returns the existing row
    # rather than piling up duplicates.
    stmt = select(AccessRequest).where(
        AccessRequest.user_id == user.id,
        AccessRequest.venue_id == venue_id,
        AccessRequest.status == AccessRequestStatus.PENDING,
        AccessRequest.event_id == req.event_id if req.event_id else AccessRequest.event_id.is_(None),
    )
    existing = (await db.execute(stmt)).scalars().first()
    if existing:
        return existing

    access_request = AccessRequest(
        user_id=user.id,
        venue_id=venue_id,
        event_id=req.event_id,
        note=(req.note or "").strip()[:255] or None,
    )
    db.add(access_request)
    await db.commit()
    await db.refresh(access_request)
    return access_request


async def list_requests(db: AsyncSession, venue_id: int, status: Optional[str] = None) -> List[AccessRequest]:
    # selectinload(.user): the admin list response reads request.user.display_name
    # (see venue_router.py) -- without eager-loading it, that access is a lazy
    # load outside of an awaitable context and raises MissingGreenlet under
    # the async engine.
    stmt = (
        select(AccessRequest)
        .where(AccessRequest.venue_id == venue_id)
        .options(selectinload(AccessRequest.user))
        .order_by(AccessRequest.created_at.desc())
    )
    if status:
        stmt = stmt.where(AccessRequest.status == AccessRequestStatus(status))
    return list((await db.execute(stmt)).scalars().all())


async def decide_request(db: AsyncSession, venue_id: int, request_id: int, approve: bool) -> Optional[AccessRequest]:
    result = await db.execute(
        select(AccessRequest)
        .where(AccessRequest.id == request_id, AccessRequest.venue_id == venue_id)
        .options(selectinload(AccessRequest.user))
    )
    access_request = result.scalars().first()
    if not access_request:
        return None
    access_request.status = AccessRequestStatus.APPROVED if approve else AccessRequestStatus.REJECTED
    access_request.decided_at = _utcnow()
    await db.commit()
    await db.refresh(access_request)
    return access_request
