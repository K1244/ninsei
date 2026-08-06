from pydantic import BaseModel, ConfigDict
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
    style: Optional[str] = None  # Guest-picked venue style tag (Pro venues only, see style_service.py)

class QueueAddPremiumRequest(QueueAddRequest):
    """Same as QueueAddRequest, but for adding a song tagged with a
    premium-only style -- style is required and the request pays
    Venue.premium_style_unlock_fee. See payment_service.unlock_premium_style_and_add."""
    style: str
    payment_method: str = "mock_card"

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
    style: Optional[str] = None
    is_autofilled: bool = False
    added_by_user: Optional[str] = "Guest"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PriorityTierResponse(BaseModel):
    id: int
    name: str
    cost: float
    priority_boost: int
    description: Optional[str]

    model_config = ConfigDict(from_attributes=True)

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

class WSMessage(BaseModel):
    type: str # 'QUEUE_UPDATED', 'PLAY_TRACK', 'PLAYER_STATUS', 'ALERT_EVENT'
    payload: dict

# --- Venue owner auth ---

class VenueRegisterRequest(BaseModel):
    venue_name: str
    email: str
    password: str

class VenueLoginRequest(BaseModel):
    email: str
    password: str

class VenueResponse(BaseModel):
    id: int
    slug: str
    name: str
    email: str
    subscription_tier: str
    active_provider: str
    host_spotify_tier: str
    premium_style_unlock_fee: float
    autoplay_enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# --- Device pairing ---

class DeviceRegisterRequest(BaseModel):
    # If the player already has a device_token in localStorage from a previous
    # visit, it sends it back so the same physical device keeps its identity
    # (and, if already claimed, doesn't need to re-pair) instead of minting a
    # brand new row every time the page reloads.
    device_token: Optional[str] = None

class DeviceRegisterResponse(BaseModel):
    device_token: str
    pairing_code: Optional[str] = None
    claimed: bool
    venue_slug: Optional[str] = None
    venue_name: Optional[str] = None

class DeviceStatusResponse(BaseModel):
    claimed: bool
    venue_slug: Optional[str] = None
    venue_name: Optional[str] = None

class DeviceClaimRequest(BaseModel):
    pairing_code: str

class DeviceResponse(BaseModel):
    id: int
    label: Optional[str]
    claimed_at: Optional[datetime]
    last_seen_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# --- Venue dashboard (owner-authenticated) ---

class VenueSettingsUpdate(BaseModel):
    name: Optional[str] = None
    active_provider: Optional[str] = None      # 'youtube' or 'spotify'
    host_spotify_tier: Optional[str] = None    # 'premium' or 'free' (simulated)
    premium_style_unlock_fee: Optional[float] = None  # Pro: flat fee to add a premium-only style
    autoplay_enabled: Optional[bool] = None    # Pro: auto-fill the queue when requests run low

class SubscriptionUpgradeRequest(BaseModel):
    tier: str  # 'free' or 'pro' (simulated -- no real billing)

# --- Venue styles (Pro-only, see style_service.py) ---

class VenueStyleCreate(BaseModel):
    name: str
    rule: str  # 'preferred' | 'premium_only' | 'prohibited'

class VenueStyleUpdate(BaseModel):
    rule: str

class VenueStyleResponse(BaseModel):
    id: int
    name: str
    rule: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# --- Revenue (see payment_service.get_revenue_summary) ---

class RevenueSummaryResponse(BaseModel):
    total_collected: float
    venue_share_total: float
    app_share_total: float
    subscription_tier: str
    revenue_share_pct: float  # fraction of new revenue the venue currently keeps
