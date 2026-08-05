from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any

from backend.app.database import get_db
from backend.app.schemas import (
    TrackSearchResult, QueueAddRequest, QueueItemResponse,
    PriorityTierResponse, SimulatePaymentRequest, PlayerEventUpdate, SubscriptionStatusRequest
)
from backend.app.media_providers.factory import MediaProviderFactory
from backend.app.media_providers.base import SpotifyPremiumRequiredException
from backend.app.services.queue_service import (
    get_current_queue_response, add_track_to_queue, advance_queue,
    skip_current_track, remove_from_queue, clear_queue, get_currently_playing_track
)
from backend.app.services.payment_service import get_priority_tiers, process_mock_payment
from backend.app.services.ws_manager import ws_manager
from backend.app.config import settings

router = APIRouter(prefix="/api", tags=["Virtual Jukebox API"])

@router.get("/search", response_model=List[TrackSearchResult])
async def search_tracks(q: str = Query(..., min_length=1), provider: str = None):
    """Search music tracks via current active media provider strategy."""
    try:
        active_provider = MediaProviderFactory.get_provider(provider)
        return await active_provider.search_tracks(q)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/queue", response_model=List[Dict[str, Any]])
async def get_queue(db: AsyncSession = Depends(get_db)):
    """Fetch current playing & queued tracks ordered by priority."""
    return await get_current_queue_response(db)

@router.post("/queue/add")
async def add_to_queue(req: QueueAddRequest, db: AsyncSession = Depends(get_db)):
    """Add a new track to the queue."""
    try:
        return await add_track_to_queue(db, req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/queue/skip")
async def skip_track(db: AsyncSession = Depends(get_db)):
    """Skip currently playing track and auto-advance to next."""
    res = await skip_current_track(db)
    return {"success": True, "next_track": res}

@router.delete("/queue/clear")
async def empty_queue(db: AsyncSession = Depends(get_db)):
    """Admin endpoint: Clear all queued items."""
    await clear_queue(db)
    return {"success": True, "message": "Queue cleared successfully."}

@router.delete("/queue/{queue_id}")
async def remove_item(queue_id: int, db: AsyncSession = Depends(get_db)):
    """Remove a specific item from the queue."""
    success = await remove_from_queue(db, queue_id)
    if not success:
        raise HTTPException(status_code=404, detail="Queue item not found.")
    return {"success": True, "message": "Queue item removed."}

@router.get("/priority-tiers", response_model=List[PriorityTierResponse])
async def list_priority_tiers(db: AsyncSession = Depends(get_db)):
    """List available mock payment priority tiers."""
    return await get_priority_tiers(db)

@router.post("/payments/simulate")
async def simulate_payment(req: SimulatePaymentRequest, db: AsyncSession = Depends(get_db)):
    """Process a simulated priority payment to bump a song in queue."""
    try:
        return await process_mock_payment(db, req)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Payment processing failed: {str(e)}")

@router.post("/player/event")
async def handle_player_event(update: PlayerEventUpdate, db: AsyncSession = Depends(get_db)):
    """Receive playback client events (e.g. track_ended, track_started, player_error)."""
    if update.event_type == "track_ended":
        print(f"[PlayerEvent] Track ended. Auto-advancing queue...")
        next_track = await advance_queue(db)
        return {"action": "advanced_queue", "next_track": next_track}
    
    elif update.event_type == "player_error":
        print(f"[PlayerEvent] Player error reported: {update.error_message}")
        await ws_manager.broadcast("ALERT_EVENT", {
            "title": "Playback Player Error",
            "type": "error",
            "message": update.error_message or "Unknown YouTube/Media player error.",
            "song_id": update.song_id
        })
        return {"action": "error_logged"}

    # Broadcast player status update
    await ws_manager.broadcast("PLAYER_STATUS", {
        "event_type": update.event_type,
        "queue_id": update.queue_id,
        "song_id": update.song_id,
        "current_time_seconds": update.current_time_seconds
    })
    return {"action": "status_broadcasted"}

@router.post("/admin/subscription-status")
async def update_subscription_status(req: SubscriptionStatusRequest, db: AsyncSession = Depends(get_db)):
    """
    Simulate host subscription status & media provider switching.
    Demonstrates handling of Spotify 403 Forbidden / Premium Required alerts.
    """
    settings.ACTIVE_PROVIDER = req.provider.lower()
    settings.HOST_SPOTIFY_TIER = req.tier.lower()

    try:
        provider = MediaProviderFactory.get_provider(req.provider)
        status_info = await provider.validate_host_account(req.tier)
        
        # Broadcast status change notification
        await ws_manager.broadcast("ALERT_EVENT", {
            "title": "Media Provider Status Changed",
            "type": "info",
            "message": status_info["message"],
            "provider": req.provider,
            "tier": req.tier
        })
        
        return {
            "status": "success",
            "active_provider": settings.ACTIVE_PROVIDER,
            "host_tier": settings.HOST_SPOTIFY_TIER,
            "details": status_info
        }

    except SpotifyPremiumRequiredException as spe:
        # Broadcast HTTP 403 Forbidden alert to Admin dashboard via WebSocket!
        alert_payload = {
            "title": "HTTP 403 Forbidden: Spotify Premium Required",
            "type": "error",
            "code": 403,
            "message": spe.message,
            "provider": "spotify",
            "tier": req.tier,
            "action_required": "Host must renew Spotify Premium subscription or switch media provider back to YouTube."
        }
        await ws_manager.broadcast("ALERT_EVENT", alert_payload)

        return {
            "status": "error_alert_sent",
            "active_provider": settings.ACTIVE_PROVIDER,
            "host_tier": settings.HOST_SPOTIFY_TIER,
            "error_code": 403,
            "detail": spe.message,
            "alert": alert_payload
        }
