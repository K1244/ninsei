"""
Membership plans (venue-admin CRUD) and the guest-facing join flow. Joining
is a mock payment, same pattern/revenue split as payment_service.py's
priority-boost and style-unlock payments -- reuses its `_split_amount` helper
rather than duplicating the Free/Pro split logic a third time.
"""
import uuid
from typing import List, Optional
from datetime import timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.models import (
    MembershipPlan, Membership, MembershipStatus, Purchase, TransactionStatus, Venue, User, VenueMode, _utcnow,
)
from backend.app.schemas import MembershipPlanCreate, MembershipPlanUpdate
from backend.app.services.payment_service import _split_amount

# How long a non-"one_time" membership stays valid before it needs renewing
# (there's no real recurring billing yet -- see PLAN.md section 14). "Renew"
# for MVP just means joining again.
_INTERVAL_VALIDITY = {
    "monthly": timedelta(days=30),
    "yearly": timedelta(days=365),
}


async def list_plans(db: AsyncSession, venue_id: int, enabled_only: bool = False) -> List[MembershipPlan]:
    stmt = select(MembershipPlan).where(MembershipPlan.venue_id == venue_id).order_by(MembershipPlan.price.asc())
    if enabled_only:
        stmt = stmt.where(MembershipPlan.enabled.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def get_plan(db: AsyncSession, venue_id: int, plan_id: int) -> Optional[MembershipPlan]:
    result = await db.execute(
        select(MembershipPlan).where(MembershipPlan.id == plan_id, MembershipPlan.venue_id == venue_id)
    )
    return result.scalars().first()


async def create_plan(db: AsyncSession, venue_id: int, req: MembershipPlanCreate) -> MembershipPlan:
    plan = MembershipPlan(
        venue_id=venue_id,
        name=req.name.strip(),
        price=req.price,
        interval=req.interval,
        perks=req.perks,
        access_level=VenueMode(req.access_level),
        qr_access_enabled=req.qr_access_enabled,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


async def update_plan(db: AsyncSession, venue_id: int, plan_id: int, req: MembershipPlanUpdate) -> Optional[MembershipPlan]:
    plan = await get_plan(db, venue_id, plan_id)
    if not plan:
        return None
    if req.name is not None:
        plan.name = req.name.strip()
    if req.price is not None:
        plan.price = req.price
    if req.interval is not None:
        plan.interval = req.interval
    if req.perks is not None:
        plan.perks = req.perks
    if req.access_level is not None:
        plan.access_level = VenueMode(req.access_level)
    if req.qr_access_enabled is not None:
        plan.qr_access_enabled = req.qr_access_enabled
    if req.enabled is not None:
        plan.enabled = req.enabled
    await db.commit()
    await db.refresh(plan)
    return plan


async def delete_plan(db: AsyncSession, venue_id: int, plan_id: int) -> bool:
    plan = await get_plan(db, venue_id, plan_id)
    if not plan:
        return False
    await db.delete(plan)
    await db.commit()
    return True


async def join_plan(db: AsyncSession, venue: Venue, user: User, plan_id: int, payment_method: str) -> dict:
    plan = await get_plan(db, venue.id, plan_id)
    if not plan or not plan.enabled:
        raise ValueError("Membership plan not found.")

    venue_amount, app_amount = _split_amount(venue, plan.price)
    txn_ref = f"TXN_{uuid.uuid4().hex[:8].upper()}"

    purchase = Purchase(
        user_id=user.id,
        venue_id=venue.id,
        kind="membership",
        membership_plan_id=plan.id,
        amount=plan.price,
        status=TransactionStatus.COMPLETED,
        payment_method=payment_method,
        transaction_reference=txn_ref,
        venue_amount=venue_amount,
        app_amount=app_amount,
    )
    db.add(purchase)

    valid_to = None
    validity = _INTERVAL_VALIDITY.get(plan.interval)
    if validity:
        valid_to = _utcnow() + validity

    membership = Membership(
        user_id=user.id,
        venue_id=venue.id,
        plan_id=plan.id,
        status=MembershipStatus.ACTIVE,
        valid_to=valid_to,
    )
    db.add(membership)

    await db.commit()
    await db.refresh(membership)

    return {
        "success": True,
        "transaction_reference": txn_ref,
        "membership_id": membership.id,
        "plan_name": plan.name,
        "valid_to": valid_to.isoformat() if valid_to else None,
        "message": f"Joined '{plan.name}' -- ${plan.price:.2f} charged (mock payment).",
    }
