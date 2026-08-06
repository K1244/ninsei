import uuid
from typing import List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from backend.app.config import settings
from backend.app.models import QueueItem, PriorityTier, Transaction, TransactionStatus, Venue
from backend.app.schemas import SimulatePaymentRequest, QueueAddPremiumRequest
from backend.app.services import style_service
from backend.app.services.queue_service import broadcast_queue_state, get_queue_item, _insert_queue_item
from backend.app.services.ws_manager import ws_manager

DEFAULT_TIERS = [
    {"name": "Standard Priority", "cost": 1.00, "priority_boost": 50, "description": "Jump ahead of standard requests."},
    {"name": "Express Bump", "cost": 2.50, "priority_boost": 150, "description": "Jump into the top 3 upcoming tracks."},
    {"name": "VIP Super Jump", "cost": 5.00, "priority_boost": 500, "description": "Immediate #1 next up guarantee."}
]

async def seed_priority_tiers_for_venue(db: AsyncSession, venue_id: int):
    """Called once, right after a venue registers (see auth_router.py) --
    tiers are per-venue pricing, not a shared global list."""
    result = await db.execute(select(PriorityTier).where(PriorityTier.venue_id == venue_id))
    existing = result.scalars().first()
    if existing:
        return
    for t in DEFAULT_TIERS:
        db.add(PriorityTier(
            venue_id=venue_id,
            name=t["name"],
            cost=t["cost"],
            priority_boost=t["priority_boost"],
            description=t["description"]
        ))
    await db.commit()

async def get_priority_tiers(db: AsyncSession, venue_id: int) -> List[PriorityTier]:
    result = await db.execute(
        select(PriorityTier).where(PriorityTier.venue_id == venue_id).order_by(PriorityTier.cost.asc())
    )
    tiers = result.scalars().all()
    if not tiers:
        # Defensive fallback -- every venue should already have tiers seeded at
        # registration, but don't leave a venue permanently stuck with none.
        await seed_priority_tiers_for_venue(db, venue_id)
        result = await db.execute(
            select(PriorityTier).where(PriorityTier.venue_id == venue_id).order_by(PriorityTier.cost.asc())
        )
        tiers = result.scalars().all()
    return tiers

def _split_amount(venue: Venue, amount: float) -> Tuple[float, float]:
    """Snapshot the venue/app revenue split for a payment made right now.
    Free venues: 100% to the app (unchanged from pre-Pro behavior). Pro
    venues: settings.PRO_VENUE_REVENUE_SHARE to the venue, the rest to the
    app. Returns (venue_amount, app_amount)."""
    if venue.subscription_tier == "pro":
        venue_amount = round(amount * settings.PRO_VENUE_REVENUE_SHARE, 2)
        return venue_amount, round(amount - venue_amount, 2)
    return 0.0, amount


async def process_mock_payment(db: AsyncSession, venue_id: int, req: SimulatePaymentRequest) -> Dict[str, Any]:
    # 1. Fetch Queue Item -- venue-scoped, so a guest of one venue can never
    # spend against another venue's queue item by guessing its id.
    queue_item = await get_queue_item(db, venue_id, req.queue_id)
    if not queue_item:
        raise ValueError(f"Queue item with ID {req.queue_id} not found.")

    # 2. Fetch Priority Tier -- likewise venue-scoped.
    t_result = await db.execute(
        select(PriorityTier).where(PriorityTier.id == req.tier_id, PriorityTier.venue_id == venue_id)
    )
    tier = t_result.scalars().first()
    if not tier:
        raise ValueError(f"Priority tier with ID {req.tier_id} not found.")

    venue = (await db.execute(select(Venue).where(Venue.id == venue_id))).scalars().first()
    venue_amount, app_amount = _split_amount(venue, tier.cost)

    # 3. Create Transaction Record
    txn_ref = f"TXN_{uuid.uuid4().hex[:8].upper()}"
    transaction = Transaction(
        venue_id=venue_id,
        queue_id=queue_item.id,
        amount=tier.cost,
        currency="USD",
        status=TransactionStatus.COMPLETED,
        payment_method=req.payment_method,
        transaction_reference=txn_ref,
        kind="priority_boost",
        venue_amount=venue_amount,
        app_amount=app_amount,
    )
    db.add(transaction)

    # 4. Update Queue Item priority score and paid amount
    queue_item.priority_score += float(tier.priority_boost)
    queue_item.paid_amount += tier.cost

    await db.commit()
    await db.refresh(queue_item)

    # 5. Broadcast updated queue state in real-time
    await broadcast_queue_state(db, venue_id)

    # 6. Send transaction notification to this venue's admin dashboard
    await ws_manager.broadcast(venue_id, "ALERT_EVENT", {
        "title": "Priority Payment Received",
        "type": "payment",
        "message": f"User paid ${tier.cost:.2f} ({tier.name}) to boost '{queue_item.title}'!",
        "transaction_ref": txn_ref,
        "new_priority_score": queue_item.priority_score
    })

    return {
        "success": True,
        "transaction_reference": txn_ref,
        "queue_id": queue_item.id,
        "song_title": queue_item.title,
        "amount": tier.cost,
        "new_priority_score": queue_item.priority_score,
        "message": f"Payment of ${tier.cost:.2f} successful! '{queue_item.title}' boosted to priority score {queue_item.priority_score:.0f}."
    }


async def unlock_premium_style_and_add(db: AsyncSession, venue_id: int, req: QueueAddPremiumRequest) -> Dict[str, Any]:
    """Pay this venue's flat premium_style_unlock_fee to add a song tagged
    with a 'premium_only' style. Re-validates the style server-side (never
    trust the client's claim that it needed unlocking) and refuses a
    'prohibited' style outright -- no fee unlocks that one."""
    venue = (await db.execute(select(Venue).where(Venue.id == venue_id))).scalars().first()
    if not venue:
        raise ValueError("Venue not found.")

    decision = await style_service.check_style_for_add(db, venue, req.style)
    if decision == "prohibited":
        raise ValueError(f"'{req.style}' is not accepted at this venue -- no payment can unlock it.")
    if decision == "allowed":
        raise ValueError(f"'{req.style}' doesn't require an unlock fee -- add it via the normal request flow.")

    fee = venue.premium_style_unlock_fee
    venue_amount, app_amount = _split_amount(venue, fee)

    queue_item = await _insert_queue_item(db, venue_id, req, style=req.style)

    txn_ref = f"TXN_{uuid.uuid4().hex[:8].upper()}"
    transaction = Transaction(
        venue_id=venue_id,
        queue_id=queue_item.id,
        amount=fee,
        currency="USD",
        status=TransactionStatus.COMPLETED,
        payment_method=req.payment_method,
        transaction_reference=txn_ref,
        kind="style_unlock",
        venue_amount=venue_amount,
        app_amount=app_amount,
    )
    db.add(transaction)
    queue_item.paid_amount += fee
    await db.commit()
    await db.refresh(queue_item)

    await broadcast_queue_state(db, venue_id)
    await ws_manager.broadcast(venue_id, "ALERT_EVENT", {
        "title": "Premium Style Unlocked",
        "type": "payment",
        "message": f"User paid ${fee:.2f} to add '{queue_item.title}' ({req.style}, premium-only style)!",
        "transaction_ref": txn_ref,
    })

    return {
        "success": True,
        "transaction_reference": txn_ref,
        "id": queue_item.id,
        "song_id": queue_item.song_id,
        "title": queue_item.title,
        "artist": queue_item.artist,
        "status": queue_item.status.value,
        "amount": fee,
        "message": f"Paid ${fee:.2f} to unlock '{req.style}' -- '{queue_item.title}' added to queue."
    }


async def get_revenue_summary(db: AsyncSession, venue: Venue) -> Dict[str, Any]:
    result = await db.execute(
        select(
            func.coalesce(func.sum(Transaction.amount), 0.0),
            func.coalesce(func.sum(Transaction.venue_amount), 0.0),
            func.coalesce(func.sum(Transaction.app_amount), 0.0),
        ).where(Transaction.venue_id == venue.id)
    )
    total, venue_total, app_total = result.one()
    return {
        "total_collected": float(total),
        "venue_share_total": float(venue_total),
        "app_share_total": float(app_total),
        "subscription_tier": venue.subscription_tier,
        "revenue_share_pct": settings.PRO_VENUE_REVENUE_SHARE if venue.subscription_tier == "pro" else 0.0,
    }
