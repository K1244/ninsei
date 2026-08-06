import io
from typing import List, Dict, Any, Optional

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.database import get_db
from backend.app.models import Venue, User
from backend.app.config import settings
from backend.app.schemas import (
    TrackSearchResult, QueueAddRequest, QueueAddPremiumRequest, PriorityTierResponse,
    SimulatePaymentRequest, VenueStyleResponse, AccessSummaryResponse, EventResponse,
    MembershipPlanResponse, MembershipJoinRequest, ProductResponse, ProductPurchaseRequest,
    AccessRequestCreate, AccessRequestResponse, QrPassResponse,
    DialogueNodeResponse, DialogueAdvanceRequest,
)
from backend.app.media_providers.factory import MediaProviderFactory
from backend.app.services.queue_service import get_current_queue_response, add_track_to_queue
from backend.app.services.payment_service import get_priority_tiers, process_mock_payment, unlock_premium_style_and_add
from backend.app.services import style_service, autoplay_service, access_service, event_service
from backend.app.services import membership_service, product_service, access_request_service, qr_service
from backend.app.services import dialogue_service
from backend.app.services.user_service import get_optional_user, require_user

# Public, slug-scoped endpoints -- what a guest's phone talks to after
# scanning the venue's QR code / opening /v/{slug}. No auth: the slug itself
# is the only thing identifying which venue's queue a request touches.
router = APIRouter(prefix="/api/v/{slug}", tags=["Guest (Venue-Scoped)"])


async def _get_venue_or_404(db: AsyncSession, slug: str) -> Venue:
    result = await db.execute(select(Venue).where(Venue.slug == slug))
    venue = result.scalars().first()
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found.")
    return venue


@router.get("/meta")
async def get_venue_meta(slug: str, db: AsyncSession = Depends(get_db)):
    """Lets the guest page confirm the slug is real and show the venue name."""
    venue = await _get_venue_or_404(db, slug)
    return {"name": venue.name, "slug": venue.slug}


@router.get("/search", response_model=List[TrackSearchResult])
async def search_tracks(
    slug: str,
    q: str = Query(..., min_length=1),
    provider: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Search music tracks via this venue's active media provider strategy."""
    venue = await _get_venue_or_404(db, slug)
    try:
        # Previously defaulted to a single global settings.ACTIVE_PROVIDER --
        # now defaults to this venue's own setting when the caller doesn't
        # explicitly override it.
        active_provider = MediaProviderFactory.get_provider(provider or venue.active_provider)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    try:
        return await active_provider.search_tracks(q)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue", response_model=List[Dict[str, Any]])
async def get_queue(slug: str, db: AsyncSession = Depends(get_db)):
    """Fetch this venue's current playing & queued tracks ordered by priority."""
    venue = await _get_venue_or_404(db, slug)
    return await get_current_queue_response(db, venue.id)


@router.get("/styles", response_model=List[VenueStyleResponse])
async def list_styles(slug: str, db: AsyncSession = Depends(get_db)):
    """Public style list for the add-song flow. Empty for Free venues, or
    Pro venues that haven't configured any styles yet."""
    venue = await _get_venue_or_404(db, slug)
    if venue.subscription_tier != "pro":
        return []
    return await style_service.list_venue_styles(db, venue.id)


@router.post("/queue/add")
async def add_to_queue(slug: str, req: QueueAddRequest, db: AsyncSession = Depends(get_db)):
    """Add a new track to this venue's queue. A style tagged 'prohibited'
    is rejected outright; one tagged 'premium_only' is rejected here too,
    with a 402 pointing the client at POST /queue/add-premium instead."""
    venue = await _get_venue_or_404(db, slug)

    decision = await style_service.check_style_for_add(db, venue, req.style)
    if decision == "prohibited":
        raise HTTPException(status_code=403, detail=f"'{req.style}' isn't accepted at this venue.")
    if decision == "needs_unlock":
        raise HTTPException(
            status_code=402,
            detail={
                "requires_unlock": True,
                "style": req.style,
                "unlock_fee": venue.premium_style_unlock_fee,
                "message": f"'{req.style}' is a premium-only style here -- pay ${venue.premium_style_unlock_fee:.2f} to add it.",
            },
        )

    try:
        result = await add_track_to_queue(db, venue.id, req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    await autoplay_service.maybe_fill_queue(db, venue.id)
    return result


@router.post("/queue/add-premium")
async def add_premium_to_queue(slug: str, req: QueueAddPremiumRequest, db: AsyncSession = Depends(get_db)):
    """Pay this venue's flat premium-style-unlock fee to add a song tagged
    with a 'premium_only' style."""
    venue = await _get_venue_or_404(db, slug)
    try:
        result = await unlock_premium_style_and_add(db, venue.id, req)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Payment processing failed: {str(e)}")
    await autoplay_service.maybe_fill_queue(db, venue.id)
    return result


@router.get("/priority-tiers", response_model=List[PriorityTierResponse])
async def list_priority_tiers(slug: str, db: AsyncSession = Depends(get_db)):
    """List this venue's mock payment priority tiers."""
    venue = await _get_venue_or_404(db, slug)
    return await get_priority_tiers(db, venue.id)


@router.post("/payments/simulate")
async def simulate_payment(slug: str, req: SimulatePaymentRequest, db: AsyncSession = Depends(get_db)):
    """Process a simulated priority payment to bump a song in this venue's queue."""
    venue = await _get_venue_or_404(db, slug)
    try:
        return await process_mock_payment(db, venue.id, req)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Payment processing failed: {str(e)}")


@router.get("/qr.svg")
async def guest_qr_code(slug: str, db: AsyncSession = Depends(get_db)):
    """Public QR code encoding this venue's guest request URL -- meant to be
    printed/displayed at the venue, no auth needed (the slug isn't sensitive)."""
    venue = await _get_venue_or_404(db, slug)
    target_url = f"{settings.PUBLIC_ORIGIN}/v/{venue.slug}" if settings.PUBLIC_ORIGIN else f"/v/{venue.slug}"
    img = qrcode.make(target_url, image_factory=qrcode.image.svg.SvgImage)
    buf = io.BytesIO()
    img.save(buf)
    return Response(content=buf.getvalue(), media_type="image/svg+xml")


# --- Clubowna: access, events, memberships, products, access requests, QR pass ---
# Everything below is scoped to this venue's slug like the jukebox endpoints
# above, but drives the community layer around it rather than the queue.

def _require_module(venue: Venue, key: str, label: str) -> None:
    if key not in venue.available_modules:
        raise HTTPException(status_code=403, detail=f"{label} isn't enabled at this venue.")


@router.get("/access", response_model=AccessSummaryResponse)
async def get_access(slug: str, db: AsyncSession = Depends(get_db), user: Optional[User] = Depends(get_optional_user)):
    """What the calling patron (identified or anonymous) can currently do at
    this venue -- drives which CTAs the venue-scene screen shows."""
    venue = await _get_venue_or_404(db, slug)
    ctx = await access_service.evaluate_access(db, venue, user)
    return AccessSummaryResponse(
        can_view_venue=ctx.can_view_venue,
        can_enter_venue=ctx.can_enter_venue,
        can_observe_event=ctx.can_observe_event and "observers" in venue.available_modules,
        can_request_access=ctx.can_request_access and "request_access" in venue.available_modules,
        can_use_jukebox=ctx.can_use_jukebox and "jukebox" in venue.available_modules,
        can_show_qr=ctx.can_show_qr and "qr_entry" in venue.available_modules,
        can_buy_product=ctx.can_buy_product and "products" in venue.available_modules,
        can_join_membership=ctx.can_join_membership and "memberships" in venue.available_modules,
        reason=ctx.reason,
        active_event=EventResponse.model_validate(ctx.active_event) if ctx.active_event else None,
    )


@router.get("/events", response_model=List[EventResponse])
async def list_public_events(slug: str, db: AsyncSession = Depends(get_db)):
    venue = await _get_venue_or_404(db, slug)
    events = await event_service.list_events(db, venue.id, public_only=True)
    return [EventResponse.model_validate(e) for e in events]


@router.get("/membership-plans", response_model=List[MembershipPlanResponse])
async def list_membership_plans(slug: str, db: AsyncSession = Depends(get_db)):
    venue = await _get_venue_or_404(db, slug)
    if "memberships" not in venue.available_modules:
        return []
    plans = await membership_service.list_plans(db, venue.id, enabled_only=True)
    return [MembershipPlanResponse.model_validate(p) for p in plans]


@router.post("/membership-plans/{plan_id}/join")
async def join_membership_plan(
    slug: str,
    plan_id: int,
    req: MembershipJoinRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    venue = await _get_venue_or_404(db, slug)
    _require_module(venue, "memberships", "Memberships")
    try:
        result = await membership_service.join_plan(db, venue, user, plan_id, req.payment_method)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    result["user_token"] = user.token
    return result


@router.get("/products", response_model=List[ProductResponse])
async def list_products(slug: str, db: AsyncSession = Depends(get_db)):
    venue = await _get_venue_or_404(db, slug)
    if "products" not in venue.available_modules:
        return []
    products = await product_service.list_products(db, venue.id, visible_only=True)
    return [ProductResponse.model_validate(p) for p in products]


@router.post("/products/{product_id}/purchase")
async def purchase_product(
    slug: str,
    product_id: int,
    req: ProductPurchaseRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    venue = await _get_venue_or_404(db, slug)
    _require_module(venue, "products", "Products")
    try:
        result = await product_service.purchase_product(db, venue, user, product_id, req.payment_method)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    result["user_token"] = user.token
    return result


@router.post("/access-requests", response_model=AccessRequestResponse)
async def request_access(
    slug: str,
    req: AccessRequestCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    venue = await _get_venue_or_404(db, slug)
    _require_module(venue, "request_access", "Request access")
    access_request = await access_request_service.create_request(db, venue.id, user, req)
    resp = AccessRequestResponse.model_validate(access_request)
    resp.user_display_name = user.display_name
    return resp


@router.get("/qr-pass", response_model=QrPassResponse)
async def get_qr_pass(slug: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_user)):
    venue = await _get_venue_or_404(db, slug)
    _require_module(venue, "qr_entry", "QR entry")
    # Deliberately unconditional: a QR pass is a digital *ID badge* (this is
    # patron X), not a proof of entitlement in itself -- anyone identified
    # can hold one, including someone mid-way through a pending access
    # request. Door staff scan it and access_service.scan_qr_pass
    # re-evaluates their *current* real entitlement (membership/event/
    # pending request) at scan time -- that's what actually decides green/
    # yellow/red, not whether this row exists. See evaluate_access's
    # comment for why merely holding one must never grant entry on its own.
    qr_pass = await qr_service.get_or_create_pass(db, venue, user)
    return qr_pass


# --- NPC dialogue (see dialogue_data.py / dialogue_service.py) -------------
# Talking to an NPC in the venue scene (Bartender/DJ/Bouncer/Hacker, see
# venue.js) round-trips through these two endpoints. Stateless like the rest
# of this router: the client always sends back which node it wants next (see
# DialogueAdvanceRequest's docstring), no server-side conversation session.

@router.get("/npcs/{npc_id}/dialogue", response_model=DialogueNodeResponse)
async def get_npc_dialogue(
    slug: str, npc_id: str, db: AsyncSession = Depends(get_db), user: Optional[User] = Depends(get_optional_user),
):
    venue = await _get_venue_or_404(db, slug)
    try:
        start_node = dialogue_service.get_start_node_id(npc_id)
        return await dialogue_service.resolve_node(db, venue, user, npc_id, start_node)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.post("/npcs/{npc_id}/dialogue/advance", response_model=DialogueNodeResponse)
async def advance_npc_dialogue(
    slug: str, npc_id: str, req: DialogueAdvanceRequest,
    db: AsyncSession = Depends(get_db), user: Optional[User] = Depends(get_optional_user),
):
    venue = await _get_venue_or_404(db, slug)
    try:
        return await dialogue_service.resolve_node(db, venue, user, npc_id, req.next, req.context)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
