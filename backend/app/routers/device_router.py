from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.schemas import (
    DeviceRegisterRequest, DeviceRegisterResponse, DeviceStatusResponse, PlayerEventUpdate,
)
from backend.app.services.device_service import (
    register_or_refresh_device, get_device_by_token, _venue_summary,
)
from backend.app.services.queue_service import advance_queue
from backend.app.services.ws_manager import ws_manager

router = APIRouter(prefix="/api/devices", tags=["Playback Devices"])


@router.post("/register", response_model=DeviceRegisterResponse)
async def register_device(req: DeviceRegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Called by the player machine on load. Sends back its existing
    localStorage device_token if it has one (so re-registering doesn't churn
    a fresh device identity every page load); gets back a token to persist
    plus a pairing code to show on screen while unclaimed.
    """
    device = await register_or_refresh_device(db, req.device_token)
    summary = await _venue_summary(db, device.venue_id)
    return DeviceRegisterResponse(
        device_token=device.device_token,
        pairing_code=device.pairing_code,
        claimed=device.venue_id is not None,
        **summary,
    )


@router.get("/{device_token}", response_model=DeviceStatusResponse)
async def device_status(device_token: str, db: AsyncSession = Depends(get_db)):
    """Polled by the player while waiting to be claimed."""
    device = await get_device_by_token(db, device_token)
    if not device:
        raise HTTPException(status_code=404, detail="Unknown device.")
    summary = await _venue_summary(db, device.venue_id)
    return DeviceStatusResponse(claimed=device.venue_id is not None, **summary)


@router.post("/{device_token}/event")
async def handle_player_event(device_token: str, update: PlayerEventUpdate, db: AsyncSession = Depends(get_db)):
    """Receive playback client events (track_ended, player_error, progress) from
    a claimed player device, scoped to whichever venue it's linked to."""
    device = await get_device_by_token(db, device_token)
    if not device or device.venue_id is None:
        raise HTTPException(status_code=404, detail="Device not found or not paired to a venue.")
    venue_id = device.venue_id

    if update.event_type == "track_ended":
        print(f"[PlayerEvent] Track ended for venue {venue_id}. Auto-advancing queue...")
        next_track = await advance_queue(db, venue_id)
        return {"action": "advanced_queue", "next_track": next_track}

    elif update.event_type == "player_error":
        print(f"[PlayerEvent] Player error reported for venue {venue_id}: {update.error_message}")
        await ws_manager.broadcast(venue_id, "ALERT_EVENT", {
            "title": "Playback Player Error",
            "type": "error",
            "message": update.error_message or "Unknown YouTube/Media player error.",
            "song_id": update.song_id
        })
        return {"action": "error_logged"}

    # Broadcast player status update to the rest of this venue's clients
    await ws_manager.broadcast(venue_id, "PLAYER_STATUS", {
        "event_type": update.event_type,
        "queue_id": update.queue_id,
        "song_id": update.song_id,
        "current_time_seconds": update.current_time_seconds
    })
    return {"action": "status_broadcasted"}
