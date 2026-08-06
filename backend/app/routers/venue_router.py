from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from backend.app.database import get_db
from backend.app.models import Venue
from backend.app.auth import get_current_venue
from backend.app.schemas import (
    DeviceClaimRequest, DeviceResponse, VenueResponse, VenueSettingsUpdate,
    SubscriptionUpgradeRequest, VenueStyleCreate, VenueStyleUpdate, VenueStyleResponse,
    RevenueSummaryResponse,
)
from backend.app.services.device_service import claim_device, list_devices, unlink_device
from backend.app.services.queue_service import skip_current_track, clear_queue, remove_from_queue
from backend.app.services.ws_manager import ws_manager
from backend.app.services import style_service, autoplay_service
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
