import time
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from backend.app.models import QueueItem, QueueStatus, User
from backend.app.schemas import QueueAddRequest, QueueItemResponse
from backend.app.services.ws_manager import ws_manager

async def get_current_queue_models(db: AsyncSession) -> List[QueueItem]:
    # Query playing track first, followed by queued tracks sorted by priority_score DESC, created_at ASC
    result = await db.execute(
        select(QueueItem)
        .where(QueueItem.status.in_([QueueStatus.PLAYING, QueueStatus.QUEUED]))
        .order_by(
            QueueItem.status != QueueStatus.PLAYING, # PLAYING comes first
            QueueItem.priority_score.desc(),
            QueueItem.created_at.asc()
        )
    )
    return result.scalars().all()

async def get_current_queue_response(db: AsyncSession) -> List[Dict[str, Any]]:
    items = await get_current_queue_models(db)
    response = []
    for item in items:
        response.append({
            "id": item.id,
            "song_id": item.song_id,
            "title": item.title,
            "artist": item.artist,
            "duration_seconds": item.duration_seconds,
            "thumbnail_url": item.thumbnail_url,
            "provider": item.provider,
            "priority_score": item.priority_score,
            "status": item.status.value,
            "paid_amount": item.paid_amount,
            "added_by_user": "Guest",
            "created_at": item.created_at.isoformat()
        })
    return response

async def get_currently_playing_track(db: AsyncSession) -> Optional[QueueItem]:
    result = await db.execute(
        select(QueueItem).where(QueueItem.status == QueueStatus.PLAYING)
    )
    return result.scalars().first()

async def broadcast_queue_state(db: AsyncSession):
    queue = await get_current_queue_response(db)
    currently_playing = next((item for item in queue if item["status"] == "playing"), None)
    
    await ws_manager.broadcast("QUEUE_UPDATED", {
        "queue": queue,
        "currently_playing": currently_playing
    })

async def add_track_to_queue(db: AsyncSession, req: QueueAddRequest) -> Dict[str, Any]:
    # Check if there is an active playing track
    playing_track = await get_currently_playing_track(db)
    
    # Initial status: if nothing is playing, make this track PLAYING immediately; otherwise QUEUED
    initial_status = QueueStatus.PLAYING if not playing_track else QueueStatus.QUEUED
    
    # Base priority score is 0.0
    queue_item = QueueItem(
        song_id=req.song_id,
        title=req.title,
        artist=req.artist,
        duration_seconds=req.duration_seconds,
        thumbnail_url=req.thumbnail_url,
        provider=req.provider,
        priority_score=0.0,
        status=initial_status,
        paid_amount=0.0
    )
    
    db.add(queue_item)
    await db.commit()
    await db.refresh(queue_item)
    
    # Broadcast updated queue to all connected clients
    await broadcast_queue_state(db)
    
    # If this new song is set to PLAYING, instruct playback client to play it
    if initial_status == QueueStatus.PLAYING:
        await ws_manager.broadcast("PLAY_TRACK", {
            "queue_id": queue_item.id,
            "song_id": queue_item.song_id,
            "title": queue_item.title,
            "artist": queue_item.artist,
            "thumbnail_url": queue_item.thumbnail_url,
            "provider": queue_item.provider,
            "duration_seconds": queue_item.duration_seconds
        })

    return {
        "id": queue_item.id,
        "song_id": queue_item.song_id,
        "title": queue_item.title,
        "artist": queue_item.artist,
        "status": queue_item.status.value,
        "message": f"Added '{queue_item.title}' to queue successfully."
    }

async def advance_queue(db: AsyncSession) -> Optional[Dict[str, Any]]:
    """Advances queue: marks current PLAYING song as COMPLETED, and sets top QUEUED song to PLAYING."""
    # 1. Mark current playing song completed
    playing_track = await get_currently_playing_track(db)
    if playing_track:
        playing_track.status = QueueStatus.COMPLETED
        await db.commit()

    # 2. Pick next highest priority queued song
    result = await db.execute(
        select(QueueItem)
        .where(QueueItem.status == QueueStatus.QUEUED)
        .order_by(QueueItem.priority_score.desc(), QueueItem.created_at.asc())
    )
    next_track = result.scalars().first()

    if next_track:
        next_track.status = QueueStatus.PLAYING
        await db.commit()
        await db.refresh(next_track)

        # Broadcast updated queue state
        await broadcast_queue_state(db)

        # Send play command to playback client
        track_payload = {
            "queue_id": next_track.id,
            "song_id": next_track.song_id,
            "title": next_track.title,
            "artist": next_track.artist,
            "thumbnail_url": next_track.thumbnail_url,
            "provider": next_track.provider,
            "duration_seconds": next_track.duration_seconds
        }
        await ws_manager.broadcast("PLAY_TRACK", track_payload)
        return track_payload
    else:
        # No more tracks in queue
        await broadcast_queue_state(db)
        await ws_manager.broadcast("PLAY_TRACK", {
            "queue_id": None,
            "song_id": None,
            "message": "Queue is empty."
        })
        return None

async def skip_current_track(db: AsyncSession):
    playing_track = await get_currently_playing_track(db)
    if playing_track:
        playing_track.status = QueueStatus.SKIPPED
        await db.commit()
    return await advance_queue(db)

async def remove_from_queue(db: AsyncSession, queue_id: int):
    result = await db.execute(select(QueueItem).where(QueueItem.id == queue_id))
    item = result.scalars().first()
    if item:
        if item.status == QueueStatus.PLAYING:
            await skip_current_track(db)
        else:
            await db.delete(item)
            await db.commit()
            await broadcast_queue_state(db)
        return True
    return False

async def clear_queue(db: AsyncSession):
    items = await get_current_queue_models(db)
    for item in items:
        await db.delete(item)
    await db.commit()
    await broadcast_queue_state(db)
    await ws_manager.broadcast("PLAY_TRACK", {
        "queue_id": None,
        "song_id": None,
        "message": "Queue cleared."
    })
