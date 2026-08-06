from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional

from backend.app.database import get_db
from backend.app.models import Venue, VenueMode, Purchase, Transaction
from backend.app.auth import get_current_venue
from backend.app.config import (
    settings, FAVORITE_GENRE_OPTIONS, FAVORITE_GENRE_KEYS,
    MODULE_OPTIONS, MODULE_KEYS, EVENT_TYPE_OPTIONS, SCENE_THEME_OPTIONS,
)
from backend.app.schemas import (
    DeviceClaimRequest, DeviceResponse, VenueResponse, VenueSettingsUpdate,
    SubscriptionUpgradeRequest, VenueStyleCreate, VenueStyleUpdate, VenueStyleResponse,
    RevenueSummaryResponse, VenueAdminSettingsUpdate, EventCreate, EventUpdate, EventResponse,
    MembershipPlanCreate, MembershipPlanUpdate, MembershipPlanResponse, ProductCreate, ProductUpdate,
    ProductResponse, AccessRequestDecision, AccessRequestResponse, QrScanRequest, QrScanResponse,
)
from backend.app.services.device_service import (
    claim_device, list_devices, unlink_device,
    get_or_create_player_link_token, regenerate_player_link_token,
)
from backend.app.services.queue_service import skip_current_track, clear_queue, remove_from_queue
from backend.app.services.ws_manager import ws_manager
from backend.app.services import style_service, autoplay_service, event_service
from backend.app.services import membership_service, product_service, access_request_service, access_service
from backend.app.services.payment_service import get_revenue_summary
from backend.app.media_providers.factory import MediaProviderFactory
from backend.app.media_providers.base import SpotifyPremiumRequiredException

router = APIRouter(prefix="/api/dashboard", tags=["Venue Dashboard"])

SUBSCRIPTION_TIERS = {"free", "pro"}


def require_pro_venue(venue: Venue = Depends(get_current_venue)) -> Venue:
    """Gate for Pro-only dashboard features (style rules, etc). Free venues
    get a clear 402 rather than a confusing empty/broken panel."""
    if venue.subscription_tier != "pro":
        raise HTTPException(status_code=402, detail="Upgrade to Pro to use this feature.")
    return venue


# --- Settings ---

@router.get("/settings", response_model=VenueResponse)
async def get_settings(venue: Venue = Depends(get_current_venue)):
    return venue


@router.get("/genre-options")
async def genre_options(venue: Venue = Depends(get_current_venue)):
    """The fixed checklist for the Favorite Genres profile setting below --
    single source of truth is config.FAVORITE_GENRE_OPTIONS so the dashboard
    never has to hardcode its own copy of the list."""
    return FAVORITE_GENRE_OPTIONS


@router.patch("/settings")
async def update_settings(
    req: VenueSettingsUpdate,
    venue: Venue = Depends(get_current_venue),
    db: AsyncSession = Depends(get_db),
):
    """
    Update venue name / active media provider / simulated host subscription
    tier. Replaces the old global-mutating admin endpoint -- this only ever
    touches the authenticated owner's own Venue row.
    """
    if req.name is not None:
        if not req.name.strip():
            raise HTTPException(status_code=400, detail="Venue name cannot be empty.")
        venue.name = req.name.strip()

    provider_changed = req.active_provider is not None and req.active_provider.lower() != venue.active_provider
    if req.active_provider is not None:
        venue.active_provider = req.active_provider.lower()
    if req.host_spotify_tier is not None:
        venue.host_spotify_tier = req.host_spotify_tier.lower()
    if req.premium_style_unlock_fee is not None:
        if req.premium_style_unlock_fee < 0:
            raise HTTPException(status_code=400, detail="Unlock fee cannot be negative.")
        venue.premium_style_unlock_fee = req.premium_style_unlock_fee
    if req.autoplay_enabled is not None:
        venue.autoplay_enabled = req.autoplay_enabled
    if req.favorite_genres is not None:
        unknown = [g for g in req.favorite_genres if g not in FAVORITE_GENRE_KEYS]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown genre(s): {', '.join(unknown)}. Supported: {sorted(FAVORITE_GENRE_KEYS)}",
            )
        # De-dupe while preserving the order the owner picked them in.
        venue.favorite_genres = list(dict.fromkeys(req.favorite_genres))

    await db.commit()
    await db.refresh(venue)

    # If the media provider (or its simulated tier) changed, re-validate the
    # host account the same way the old global admin endpoint did, including
    # the simulated Spotify-Premium-required 403 flow.
    if provider_changed or req.host_spotify_tier is not None:
        try:
            provider = MediaProviderFactory.get_provider(venue.active_provider)
            status_info = await provider.validate_host_account(venue.host_spotify_tier)
            await ws_manager.broadcast(venue.id, "ALERT_EVENT", {
                "title": "Media Provider Status Changed",
                "type": "info",
                "message": status_info["message"],
                "provider": venue.active_provider,
                "tier": venue.host_spotify_tier,
            })
            return {"status": "success", "venue": VenueResponse.model_validate(venue), "details": status_info}
        except SpotifyPremiumRequiredException as spe:
            alert_payload = {
                "title": "HTTP 403 Forbidden: Spotify Premium Required",
                "type": "error",
                "code": 403,
                "message": spe.message,
                "provider": "spotify",
                "tier": venue.host_spotify_tier,
                "action_required": "Renew Spotify Premium or switch the media provider back to YouTube.",
            }
            await ws_manager.broadcast(venue.id, "ALERT_EVENT", alert_payload)
            return {
                "status": "error_alert_sent",
                "venue": VenueResponse.model_validate(venue),
                "error_code": 403,
                "detail": spe.message,
                "alert": alert_payload,
            }

    return {"status": "success", "venue": VenueResponse.model_validate(venue)}


@router.post("/subscription/upgrade")
async def upgrade_subscription(
    req: SubscriptionUpgradeRequest,
    venue: Venue = Depends(get_current_venue),
    db: AsyncSession = Depends(get_db),
):
    """Simulated billing only -- no real payment processor involved, same
    spirit as the guest-facing mock priority-boost payments."""
    tier = req.tier.lower()
    if tier not in SUBSCRIPTION_TIERS:
        raise HTTPException(status_code=400, detail=f"Unknown tier '{req.tier}'. Supported: {sorted(SUBSCRIPTION_TIERS)}")
    venue.subscription_tier = tier
    await db.commit()
    await db.refresh(venue)
    return {"success": True, "subscription_tier": venue.subscription_tier}


# --- Devices ---

def _build_player_link_url(venue: Venue, token: str) -> str:
    path = f"/play/{venue.slug}/{token}"
    return f"{settings.PUBLIC_ORIGIN}{path}" if settings.PUBLIC_ORIGIN else path


@router.get("/player-link")
async def get_player_link(venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    """Copyable, venue-specific playback-device URL -- opening it in the
    TV/tablet's browser auto-claims that device, skipping the manual
    pairing-code flow below entirely. See device_service.link_device_via_token."""
    token = await get_or_create_player_link_token(db, venue)
    return {"url": _build_player_link_url(venue, token)}


@router.post("/player-link/regenerate")
async def regenerate_player_link(venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    """Invalidates the previous link (e.g. it got shared somewhere it
    shouldn't have) -- devices already linked keep working."""
    token = await regenerate_player_link_token(db, venue)
    return {"url": _build_player_link_url(venue, token)}


@router.get("/devices", response_model=List[DeviceResponse])
async def get_devices(venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    return await list_devices(db, venue)


@router.post("/devices/claim", response_model=DeviceResponse)
async def claim(
    req: DeviceClaimRequest,
    venue: Venue = Depends(get_current_venue),
    db: AsyncSession = Depends(get_db),
):
    code = req.pairing_code.strip()
    try:
        device = await claim_device(db, venue, code)
    except PermissionError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return device


@router.delete("/devices/{device_id}")
async def unlink(
    device_id: int,
    venue: Venue = Depends(get_current_venue),
    db: AsyncSession = Depends(get_db),
):
    success = await unlink_device(db, venue, device_id)
    if not success:
        raise HTTPException(status_code=404, detail="Device not found.")
    return {"success": True, "message": "Device unlinked."}


# --- Venue styles (Pro-only) ---

@router.get("/styles", response_model=List[VenueStyleResponse])
async def list_styles(venue: Venue = Depends(require_pro_venue), db: AsyncSession = Depends(get_db)):
    return await style_service.list_venue_styles(db, venue.id)


@router.post("/styles", response_model=VenueStyleResponse)
async def create_style(
    req: VenueStyleCreate,
    venue: Venue = Depends(require_pro_venue),
    db: AsyncSession = Depends(get_db),
):
    """Create or update (upsert by name, case-insensitive) one of this venue's styles."""
    try:
        return await style_service.upsert_style(db, venue.id, req.name, req.rule)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


@router.patch("/styles/{style_id}", response_model=VenueStyleResponse)
async def update_style(
    style_id: int,
    req: VenueStyleUpdate,
    venue: Venue = Depends(require_pro_venue),
    db: AsyncSession = Depends(get_db),
):
    try:
        style = await style_service.update_style_rule(db, venue.id, style_id, req.rule)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    if not style:
        raise HTTPException(status_code=404, detail="Style not found.")
    return style


@router.delete("/styles/{style_id}")
async def delete_style(
    style_id: int,
    venue: Venue = Depends(require_pro_venue),
    db: AsyncSession = Depends(get_db),
):
    success = await style_service.delete_style(db, venue.id, style_id)
    if not success:
        raise HTTPException(status_code=404, detail="Style not found.")
    return {"success": True, "message": "Style removed."}


# --- Revenue ---

@router.get("/revenue/summary", response_model=RevenueSummaryResponse)
async def revenue_summary(venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    """Available to every venue -- Free venues just see 0% venue / 100% app,
    same numbers as always, so there's nothing hidden about what upgrading changes."""
    return await get_revenue_summary(db, venue)


# --- Queue moderation ---

@router.post("/queue/skip")
async def skip_track(venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    """Skip the currently playing track and auto-advance to the next."""
    res = await skip_current_track(db, venue.id)
    await autoplay_service.maybe_fill_queue(db, venue.id)
    return {"success": True, "next_track": res}


@router.delete("/queue/clear")
async def empty_queue(venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    """Clear all queued items for this venue."""
    await clear_queue(db, venue.id)
    return {"success": True, "message": "Queue cleared successfully."}


@router.delete("/queue/{queue_id}")
async def remove_item(
    queue_id: int,
    venue: Venue = Depends(get_current_venue),
    db: AsyncSession = Depends(get_db),
):
    """Remove a specific item from this venue's queue."""
    success = await remove_from_queue(db, venue.id, queue_id)
    if not success:
        raise HTTPException(status_code=404, detail="Queue item not found.")
    return {"success": True, "message": "Queue item removed."}


# ============================================================
# Clubowna: community layer admin (venue identity, modules,
# events, memberships, products, access requests, QR scanner)
# ============================================================

# --- Option lists (single source of truth -- see config.py) ---

@router.get("/module-options")
async def module_options(venue: Venue = Depends(get_current_venue)):
    return MODULE_OPTIONS


@router.get("/event-type-options")
async def event_type_options(venue: Venue = Depends(get_current_venue)):
    return EVENT_TYPE_OPTIONS


@router.get("/scene-theme-options")
async def scene_theme_options(venue: Venue = Depends(get_current_venue)):
    return SCENE_THEME_OPTIONS


# --- Venue identity / mode / modules ---

@router.patch("/community-settings", response_model=VenueResponse)
async def update_community_settings(
    req: VenueAdminSettingsUpdate,
    venue: Venue = Depends(get_current_venue),
    db: AsyncSession = Depends(get_db),
):
    """Separate from PATCH /settings above (jukebox/media-provider fields) --
    this is the venue's identity/access-mode/module-toggle side of things."""
    if req.description is not None:
        venue.description = req.description.strip() or None
    if req.address is not None:
        venue.address = req.address.strip() or None
    if req.scene_theme is not None:
        venue.scene_theme = req.scene_theme.strip() or venue.scene_theme
    if req.mode is not None:
        try:
            venue.mode = VenueMode(req.mode)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown mode '{req.mode}'. Supported: {[m.value for m in VenueMode]}")
    if req.available_modules is not None:
        unknown = [m for m in req.available_modules if m not in MODULE_KEYS]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown module(s): {', '.join(unknown)}. Supported: {sorted(MODULE_KEYS)}")
        venue.available_modules = list(dict.fromkeys(req.available_modules))

    await db.commit()
    await db.refresh(venue)
    return venue


# --- Events ---

@router.get("/events", response_model=List[EventResponse])
async def admin_list_events(venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    return await event_service.list_events(db, venue.id)


@router.post("/events", response_model=EventResponse)
async def admin_create_event(req: EventCreate, venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    try:
        return await event_service.create_event(db, venue.id, req)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


@router.patch("/events/{event_id}", response_model=EventResponse)
async def admin_update_event(
    event_id: int, req: EventUpdate, venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db),
):
    try:
        event = await event_service.update_event(db, venue.id, event_id, req)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    return event


@router.delete("/events/{event_id}")
async def admin_delete_event(event_id: int, venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    success = await event_service.delete_event(db, venue.id, event_id)
    if not success:
        raise HTTPException(status_code=404, detail="Event not found.")
    return {"success": True, "message": "Event removed."}


# --- Membership plans ---

@router.get("/membership-plans", response_model=List[MembershipPlanResponse])
async def admin_list_plans(venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    return await membership_service.list_plans(db, venue.id)


@router.post("/membership-plans", response_model=MembershipPlanResponse)
async def admin_create_plan(req: MembershipPlanCreate, venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    try:
        return await membership_service.create_plan(db, venue.id, req)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


@router.patch("/membership-plans/{plan_id}", response_model=MembershipPlanResponse)
async def admin_update_plan(
    plan_id: int, req: MembershipPlanUpdate, venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db),
):
    try:
        plan = await membership_service.update_plan(db, venue.id, plan_id, req)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    if not plan:
        raise HTTPException(status_code=404, detail="Membership plan not found.")
    return plan


@router.delete("/membership-plans/{plan_id}")
async def admin_delete_plan(plan_id: int, venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    success = await membership_service.delete_plan(db, venue.id, plan_id)
    if not success:
        raise HTTPException(status_code=404, detail="Membership plan not found.")
    return {"success": True, "message": "Membership plan removed."}


# --- Products ---

@router.get("/products", response_model=List[ProductResponse])
async def admin_list_products(venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    return await product_service.list_products(db, venue.id)


@router.post("/products", response_model=ProductResponse)
async def admin_create_product(req: ProductCreate, venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    return await product_service.create_product(db, venue.id, req)


@router.patch("/products/{product_id}", response_model=ProductResponse)
async def admin_update_product(
    product_id: int, req: ProductUpdate, venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db),
):
    product = await product_service.update_product(db, venue.id, product_id, req)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")
    return product


@router.delete("/products/{product_id}")
async def admin_delete_product(product_id: int, venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    success = await product_service.delete_product(db, venue.id, product_id)
    if not success:
        raise HTTPException(status_code=404, detail="Product not found.")
    return {"success": True, "message": "Product removed."}


# --- Access requests ---

@router.get("/access-requests", response_model=List[AccessRequestResponse])
async def admin_list_access_requests(
    status: Optional[str] = None, venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db),
):
    try:
        requests = await access_request_service.list_requests(db, venue.id, status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown status '{status}'.")
    out = []
    for r in requests:
        resp = AccessRequestResponse.model_validate(r)
        resp.user_display_name = r.user.display_name if r.user else None
        out.append(resp)
    return out


@router.post("/access-requests/{request_id}/decide", response_model=AccessRequestResponse)
async def admin_decide_access_request(
    request_id: int, req: AccessRequestDecision, venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db),
):
    access_request = await access_request_service.decide_request(db, venue.id, request_id, req.approve)
    if not access_request:
        raise HTTPException(status_code=404, detail="Access request not found.")
    resp = AccessRequestResponse.model_validate(access_request)
    resp.user_display_name = access_request.user.display_name if access_request.user else None
    return resp


# --- QR scanner (staff/door) ---

@router.post("/qr-scan", response_model=QrScanResponse)
async def scan_qr(req: QrScanRequest, venue: Venue = Depends(get_current_venue), db: AsyncSession = Depends(get_db)):
    """Staff-facing scanner endpoint -- gated behind the owner's own session
    for MVP (see PLAN.md's "keep 1 login = 1 venue" pragmatic call; a
    separate staff-account role is future scope). Returns green/yellow/red
    per PLAN.md section 8."""
    result = await access_service.scan_qr_pass(db, venue, req.token)
    return QrScanResponse(**result)
