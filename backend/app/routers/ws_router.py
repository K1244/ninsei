from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import json
import asyncio

from backend.app.database import AsyncSessionLocal
from backend.app.services.ws_manager import ws_manager
from backend.app.services.queue_service import (
    get_current_queue_response, advance_queue, skip_current_track, get_currently_playing_track
)

router = APIRouter(tags=["WebSockets"])

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    
    # Send initial state on connection
    async with AsyncSessionLocal() as db:
        queue = await get_current_queue_response(db)
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

    try:
        while True:
            data_text = await websocket.receive_text()
            try:
                msg = json.loads(data_text)
                msg_type = msg.get("type")
                payload = msg.get("payload", {})
                
                async with AsyncSessionLocal() as db:
                    if msg_type == "REQUEST_QUEUE":
                        queue = await get_current_queue_response(db)
                        currently_playing = next((item for item in queue if item["status"] == "playing"), None)
                        await websocket.send_text(json.dumps({
                            "type": "QUEUE_UPDATED",
                            "payload": {"queue": queue, "currently_playing": currently_playing}
                        }))

                    elif msg_type == "PLAYER_TRACK_ENDED":
                        await advance_queue(db)

                    elif msg_type == "PLAYER_STATUS":
                        # Relay playback progress timestamp to all other clients
                        await ws_manager.broadcast("PLAYER_STATUS", payload)

                    elif msg_type == "SKIP_TRACK":
                        await skip_current_track(db)

            except json.JSONDecodeError:
                pass
            except Exception as e:
                print(f"[WebSocket Router Error] {e}")

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
