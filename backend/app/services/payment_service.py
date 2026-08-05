import uuid
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.app.models import QueueItem, PriorityTier, Transaction, TransactionStatus
from backend.app.schemas import SimulatePaymentRequest
from backend.app.services.queue_service import broadcast_queue_state
from backend.app.services.ws_manager import ws_manager

DEFAULT_TIERS = [
    {"name": "Standard Priority", "cost": 1.00, "priority_boost": 50, "description": "Jump ahead of standard requests."},
    {"name": "Express Bump", "cost": 2.50, "priority_boost": 150, "description": "Jump into the top 3 upcoming tracks."},
    {"name": "VIP Super Jump", "cost": 5.00, "priority_boost": 500, "description": "Immediate #1 next up guarantee."}
]

async def seed_priority_tiers(db: AsyncSession):
    result = await db.execute(select(PriorityTier))
    existing = result.scalars().all()
    if not existing:
        for t in DEFAULT_TIERS:
            tier = PriorityTier(
                name=t["name"],
                cost=t["cost"],
                priority_boost=t["priority_boost"],
                description=t["description"]
            )
            db.add(tier)
        await db.commit()

async def get_priority_tiers(db: AsyncSession) -> List[PriorityTier]:
    result = await db.execute(select(PriorityTier).order_by(PriorityTier.cost.asc()))
    tiers = result.scalars().all()
    if not tiers:
        await seed_priority_tiers(db)
        result = await db.execute(select(PriorityTier).order_by(PriorityTier.cost.asc()))
        tiers = result.scalars().all()
    return tiers

async def process_mock_payment(db: AsyncSession, req: SimulatePaymentRequest) -> Dict[str, Any]:
    # 1. Fetch Queue Item
    q_result = await db.execute(select(QueueItem).where(QueueItem.id == req.queue_id))
    queue_item = q_result.scalars().first()
    if not queue_item:
        raise ValueError(f"Queue item with ID {req.queue_id} not found.")

    # 2. Fetch Priority Tier
    t_result = await db.execute(select(PriorityTier).where(PriorityTier.id == req.tier_id))
    tier = t_result.scalars().first()
    if not tier:
        raise ValueError(f"Priority tier with ID {req.tier_id} not found.")

    # 3. Create Transaction Record
    txn_ref = f"TXN_{uuid.uuid4().hex[:8].upper()}"
    transaction = Transaction(
        queue_id=queue_item.id,
        user_id=None, # Guest user
        amount=tier.cost,
        currency="USD",
        status=TransactionStatus.COMPLETED,
        payment_method=req.payment_method,
        transaction_reference=txn_ref
    )
    db.add(transaction)

    # 4. Update Queue Item priority score and paid amount
    queue_item.priority_score += float(tier.priority_boost)
    queue_item.paid_amount += tier.cost
    
    await db.commit()
    await db.refresh(queue_item)

    # 5. Broadcast updated queue state in real-time
    await broadcast_queue_state(db)

    # 6. Send transaction notification to Admin dashboard
    await ws_manager.broadcast("ALERT_EVENT", {
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
