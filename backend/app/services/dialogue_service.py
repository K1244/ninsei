"""
NPC dialogue engine for the venue scene -- walks the trees defined in
dialogue_data.py, and (for nodes with an `action`) fills in a line/choices
from live DB state. Stateless like the rest of the guest-facing API: the
caller round-trips which node it wants rendered next (see
schemas.DialogueAdvanceRequest's docstring) rather than the server holding
a conversation session.

The Hacker's queue-skip mechanic lives here as three actions (hacker_greet /
hacker_confirm / hacker_pay) rather than as data, since it has real game
effects (moving a QueueItem's priority, spending money) that don't belong in
a plain-data file -- see dialogue_data.py's module docstring for how the two
fit together. Everything else (bartender/DJ/bouncer) is read-only flavor
sourced from services that already exist.
"""
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.dialogue_data import NPCS
from backend.app.models import (
    Membership, QueueStatus, Transaction, TransactionStatus, User, Venue,
)
from backend.app.schemas import SimulatePaymentRequest
from backend.app.services import access_service, membership_service, payment_service, product_service, queue_service


def get_start_node_id(npc_id: str) -> str:
    npc = NPCS.get(npc_id)
    if not npc:
        raise ValueError(f"Unknown NPC '{npc_id}'.")
    return npc["start"]


async def resolve_node(
    db: AsyncSession, venue: Venue, user: Optional[User], npc_id: str, node_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> dict:
    npc = NPCS.get(npc_id)
    if not npc:
        raise ValueError(f"Unknown NPC '{npc_id}'.")
    node_def = npc["nodes"].get(node_id)
    if not node_def:
        raise ValueError(f"Unknown dialogue node '{node_id}' for '{npc_id}'.")

    if "action" in node_def:
        fn = _ACTIONS.get(node_def["action"])
        if not fn:
            raise ValueError(f"Unknown dialogue action '{node_def['action']}'.")
        rendered = await fn(db, venue, user, context or {})
        line = rendered["line"]
        choices = rendered.get("choices")
        if choices is None:
            choices = node_def.get("choices", [])
    else:
        line = node_def["line"]
        choices = node_def.get("choices", [])

    return {
        "npc_id": npc_id,
        "node": node_id,
        "speaker": npc["display_name"],
        "avatar": npc["avatar"],
        "line": line,
        "choices": choices,
    }


# --- Flavor actions (read-only, reuse existing services) -------------------

async def _show_products(db, venue, user, context) -> dict:
    products = await product_service.list_products(db, venue.id, visible_only=True)
    if not products:
        return {"line": "Nothing on the board yet -- ask and I'll sort you out."}
    listing = "; ".join(f"{p.name} (${p.price:.2f})" for p in products)
    return {"line": f"Tonight's board: {listing}."}


async def _show_event_program(db, venue, user, context) -> dict:
    event = await access_service.get_active_event(db, venue.id)
    if not event:
        return {"line": "Quiet tonight -- just the resident selection."}
    when = event.start_at.strftime("%H:%M") if event.start_at else "later"
    organizer = f", hosted by {event.organizer_name}" if event.organizer_name else ""
    return {"line": f"Tonight: \"{event.title}\" ({event.type}){organizer} -- kicking off {when}."}


async def _bouncer_status(db, venue, user, context) -> dict:
    ctx = await access_service.evaluate_access(db, venue, user)
    return {"line": ctx.reason or "Not happening tonight."}


# --- Hacker queue-skip mechanic ---------------------------------------------

async def _hacker_tier(db: AsyncSession, venue: Venue, user: Optional[User]) -> str:
    """The player's standing with the Hacker, per PLAN.md's follow-up spec:
    driven by their own membership at *this* venue, not luck. No membership
    at all -> low (won't talk). A membership, but not this venue's top-priced
    plan -> mid (wants paying). The venue's top-priced plan -> high (does it
    for free). A venue with no membership plans at all has nothing to prove
    status with, so it defaults to mid rather than low or high."""
    # Rank against *every* plan this venue has ever offered (not just
    # currently-enabled ones), so an existing membership on a plan the venue
    # later disabled still counts for ranking purposes. Checked before the
    # identity/membership checks below: a venue with no membership tiers at
    # all makes "no membership" true for literally everyone, so it's not a
    # meaningful low-status signal there -- mid for everyone instead.
    all_plans = await membership_service.list_plans(db, venue.id)
    if not all_plans:
        return "mid"

    if user is None:
        return "low"
    result = await db.execute(
        select(Membership).where(Membership.user_id == user.id, Membership.venue_id == venue.id)
    )
    active_memberships = [m for m in result.scalars().all() if m.is_active]
    if not active_memberships:
        return "low"

    top_price = max(p.price for p in all_plans)
    plan_price_by_id = {p.id: p.price for p in all_plans}
    if any(plan_price_by_id.get(m.plan_id) == top_price for m in active_memberships):
        return "high"
    return "mid"


async def _hacker_greet(db, venue, user, context) -> dict:
    tier = await _hacker_tier(db, venue, user)
    if tier == "low":
        return {
            "line": "Do I know you? ...No. Move along.",
            "choices": [{"label": "Fine.", "end": True}],
        }

    queue_items = await queue_service.get_current_queue_models(db, venue.id)
    queued = [q for q in queue_items if q.status == QueueStatus.QUEUED]
    if not queued:
        return {
            "line": "Queue's empty. Nothing for me to touch.",
            "choices": [{"label": "Fine.", "end": True}],
        }

    intro = ("Word is you're good for it. Which track needs... help?" if tier == "high" else
             "I can move a track up the queue. For a price. Which one?")
    choices = [
        {"label": f"\"{q.title}\" -- {q.artist}", "next": "confirm_hack", "context": {"queue_id": q.id}}
        for q in queued[:8]  # cap the picker to a sane conversation length
    ]
    choices.append({"label": "Never mind.", "end": True})
    return {"line": intro, "choices": choices}


async def _hacker_confirm(db, venue, user, context) -> dict:
    queue_id = context.get("queue_id")
    item = await queue_service.get_queue_item(db, venue.id, queue_id) if queue_id else None
    if not item:
        return {"line": "That one's gone. Try again later.", "choices": [{"label": "Fine.", "end": True}]}

    # Re-derive the tier from scratch rather than trusting anything about the
    # earlier greeting -- a membership could've lapsed mid-conversation, and
    # this is the node that actually spends money or grants a free favor.
    tier = await _hacker_tier(db, venue, user)
    if tier == "low":
        return {"line": "Changed my mind. Not happening.", "choices": [{"label": "Fine.", "end": True}]}

    if tier == "high":
        tiers = await payment_service.get_priority_tiers(db, venue.id)
        best = max(tiers, key=lambda t: t.priority_boost) if tiers else None
        boost = best.priority_boost if best else 500
        item.priority_score += float(boost)
        db.add(Transaction(
            venue_id=venue.id, queue_id=item.id, amount=0.0, currency="USD",
            status=TransactionStatus.COMPLETED, payment_method="favor",
            transaction_reference=f"TXN_{uuid.uuid4().hex[:8].upper()}",
            kind="hacker_favor", venue_amount=0.0, app_amount=0.0,
        ))
        await db.commit()
        await db.refresh(item)
        await queue_service.broadcast_queue_state(db, venue.id)
        return {
            "line": f"Say less. \"{item.title}\" just jumped the line. Don't tell anyone.",
            "choices": [{"label": "Nice.", "end": True}],
        }

    # mid -- offer this venue's existing paid priority tiers as the "bribe".
    tiers = await payment_service.get_priority_tiers(db, venue.id)
    if not tiers:
        return {"line": "No way for you to pay me right now. Come back later.", "choices": [{"label": "Fine.", "end": True}]}
    choices = [
        {"label": f"{t.name} -- ${t.cost:.2f}", "next": "pay_hack", "context": {"queue_id": item.id, "tier_id": t.id}}
        for t in tiers
    ]
    choices.append({"label": "Never mind.", "end": True})
    return {"line": f"I can move \"{item.title}\" up. Pick your poison:", "choices": choices}


async def _hacker_pay(db, venue, user, context) -> dict:
    queue_id = context.get("queue_id")
    tier_id = context.get("tier_id")
    if not queue_id or not tier_id or await _hacker_tier(db, venue, user) == "low":
        return {"line": "Deal's off.", "choices": [{"label": "Fine.", "end": True}]}

    try:
        result = await payment_service.process_mock_payment(
            db, venue.id, SimulatePaymentRequest(queue_id=queue_id, tier_id=tier_id, payment_method="mock_card"),
        )
    except ValueError as ve:
        return {"line": f"Something's off: {ve}", "choices": [{"label": "OK.", "end": True}]}

    return {
        "line": f"Paid in full. \"{result['song_title']}\" is moving. Pleasure doing business.",
        "choices": [{"label": "Thanks.", "end": True}],
    }


_ACTIONS = {
    "show_products": _show_products,
    "show_event_program": _show_event_program,
    "bouncer_status": _bouncer_status,
    "hacker_greet": _hacker_greet,
    "hacker_confirm": _hacker_confirm,
    "hacker_pay": _hacker_pay,
}
