from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Cookie
from typing import Optional, Tuple
from sqlalchemy import select
import json

from backend.app.database import AsyncSessionLocal
from backend.app.models import Venue, DeviceLink
from backend.app.auth import verify_session_token
from backend.app.services.ws_manager import ws_manager
from backend.app.services.queue_service import (
    get_current_queue_response, advance_queue, skip_current_track
)
from backend.app.services import autoplay_service

router = APIRouter(tags=["WebSockets"])

# Message types only an "owner" (dashboard) or "player" (paired playback
# device) connection may send. A guest connected to /v/{slug} can request the
# current queue but must not be able to skip/end tracks just by opening
# devtools -- previously (pre-multi-tenant) *any* connected client could send
# these and it was honored.
_PRIVILEGED_MESSAGE_TYPES = {"PLAYER_TRACK_ENDED", "PLAYER_STATUS", "SKIP_TRACK"}


async def _resolve_venue_and_role(
    venue_slug: Optional[str],
    device_token: Optional[str],
    venue_session: Optional[str],
) -> Tuple[Optional[int], Optional[str]]:
    async with AsyncSessionLocal() as db:
        if venue_slug:
            result = await db.execute(select(Venue).where(Venue.slug == venue_slug))
            venue = result.scalars().first()
            if venue:
                return venue.id, "guest"
            return None, None

        if device_token:
            result = await db.execute(select(DeviceLink).where(DeviceLink.device_token == device_token))
            device = result.scalars().first()
            if device and device.venue_id is not None:
                return device.venue_id, "player"
            return None, None

        if venue_session:
            venue_id = verify_session_token(venue_session)
            if venue_id is not None:
                result = await db.execute(select(Venue).where(Venue.id == venue_id))
                if result.scalars().first():
                    return venue_id, "owner"
            return None, None

    return None, None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    venue: Optional[str] = Query(default=None),
    device_token: Optional[str] = Query(default=None),
    venue_session: Optional[str] = Cookie(default=None),
):
    venue_id, role = await _resolve_venue_and_role(venue, device_token, venue_session)
    if venue_id is None:
        # No valid ?venue=, ?device_token=, or owner session cookie -- refuse
        # the connection rather than guessing a tenant.
        await websocket.close(code=1008)  # policy violation
        return

    await ws_manager.connect(websocket, venue_id, role)

    try:
        # Send initial state on connection
        async with AsyncSessionLocal() as db:
            queue = await get_current_queue_response(db, venue_id)
            currently_playing = next((item for item in queue if item["status"] == "playing"), None)

            await websocket.send_text(json.dumps({
                "type": "QUEUE_UPDATED",
                "payload": {
                    "queue": queue,
                    "currently_playing": currently_playing
                }
            }))

            if currently_playing:
                await websocket.send_text(json.dumps({
                    "type": "PLAY_TRACK",
                    "payload": {
                        "queue_id": currently_playing["id"],
                        "song_id": currently_playing["song_id"],
                        "title": currently_playing["title"],
                        "artist": currently_playing["artist"],
                        "thumbnail_url": currently_playing["thumbnail_url"],
                        "provider": currently_playing["provider"],
                        "duration_seconds": currently_playing["duration_seconds"]
                    }
                }))

        while True:
            data_text = await websocket.receive_text()
            try:
                msg = json.loads(data_text)
                msg_type = msg.get("type")
                payload = msg.get("payload", {})

                if msg_type in _PRIVILEGED_MESSAGE_TYPES and role not in ("owner", "player"):
                    continue  # silently ignore -- a guest connection has no business sending these

                async with AsyncSessionLocal() as db:
                    if msg_type == "REQUEST_QUEUE":
                        queue = await get_current_queue_response(db, venue_id)
                        currently_playing = next((item for item in queue if item["status"] == "playing"), None)
                        await websocket.send_text(json.dumps({
                            "type": "QUEUE_UPDATED",
                            "payload": {"queue": queue, "currently_playing": currently_playing}
                        }))

                    elif msg_type == "PLAYER_TRACK_ENDED":
                        await advance_queue(db, venue_id)
                        await autoplay_service.maybe_fill_queue(db, venue_id)

                    elif msg_type == "PLAYER_STATUS":
                        # Relay playback progress timestamp to the rest of this venue's clients
                        await ws_manager.broadcast(venue_id, "PLAYER_STATUS", payload)

                    elif msg_type == "SKIP_TRACK":
                        await skip_current_track(db, venue_id)

            except json.JSONDecodeError:
                pass
            except WebSocketDisconnect:
                raise
            except Exception as e:
                print(f"[WebSocket Router Error] {e}")

    except WebSocketDisconnect:
        pass
    except Exception as e:
        # Client can vanish mid-send (e.g. tab closed while we're pushing initial
        # state) which surfaces as a generic connection error rather than a clean
        # WebSocketDisconnect. Treat it the same: just drop the connection.
        print(f"[WebSocket] Connection ended unexpectedly: {e}")
    finally:
        ws_manager.disconnect(websocket, venue_id)
