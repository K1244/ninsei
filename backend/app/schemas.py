from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class TrackSearchResult(BaseModel):
    song_id: str
    title: str
    artist: str
    duration_seconds: int
    thumbnail_url: str
    provider: str = "youtube"

class QueueAddRequest(BaseModel):
    song_id: str
    title: str
    artist: str
    duration_seconds: int = 180
    thumbnail_url: str
    provider: str = "youtube"
    user_name: Optional[str] = "Guest User"

class QueueItemResponse(BaseModel):
    id: int
    song_id: str
    title: str
    artist: str
    duration_seconds: int
    thumbnail_url: Optional[str]
    provider: str
    priority_score: float
    status: str
    paid_amount: float
    added_by_user: Optional[str] = "Guest"
    created_at: datetime

    class Config:
        from_attributes = True

class PriorityTierResponse(BaseModel):
    id: int
    name: str
    cost: float
    priority_boost: int
    description: Optional[str]

    class Config:
        from_attributes = True

class SimulatePaymentRequest(BaseModel):
    queue_id: int
    tier_id: int
    card_name: str = "Jukebox Guest"
    payment_method: str = "mock_card"

class PlayerEventUpdate(BaseModel):
    event_type: str # 'track_started', 'track_ended', 'track_paused', 'player_error'
    queue_id: Optional[int] = None
    song_id: Optional[str] = None
    current_time_seconds: Optional[float] = 0.0
    error_message: Optional[str] = None

class SubscriptionStatusRequest(BaseModel):
    provider: str # 'youtube' or 'spotify'
    tier: str     # 'premium' or 'free'

class WSMessage(BaseModel):
    type: str # 'QUEUE_UPDATED', 'PLAY_TRACK', 'PLAYER_STATUS', 'ALERT_EVENT'
    payload: dict
