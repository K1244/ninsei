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
    favorite_genres: List[str] = []
    created_at: datetime

    # Clubowna community-layer fields (see VenueAdminSettingsUpdate /
    # PATCH /api/dashboard/community-settings below) -- included here too
    # so the dashboard can read current values straight off GET /api/auth/me
    # without a second round trip.
    description: Optional[str] = None
    address: Optional[str] = None
    scene_theme: str = "pub"
    mode: str = "public"
    available_modules: List[str] = []

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

class DeviceLinkRequest(BaseModel):
    # Sent by the player page when it's opened at /play/<slug>/<token> --
    # the copyable one-click link from the dashboard (see venue_router.py's
    # /player-link). Auto-claims the device with no code entry needed.
    slug: str
    key: str
    device_token: Optional[str] = None

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
    favorite_genres: Optional[List[str]] = None  # keys from config.FAVORITE_GENRE_OPTIONS; nudges autoplay

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


# --- Clubowna: venue admin (community/access layer) ---

class VenueAdminSettingsUpdate(BaseModel):
    """Extends VenueSettingsUpdate above with the new community-OS fields.
    Kept as its own model rather than growing VenueSettingsUpdate so the
    jukebox-only fields and the venue-identity fields stay easy to tell apart."""
    description: Optional[str] = None
    address: Optional[str] = None
    scene_theme: Optional[str] = None
    mode: Optional[str] = None  # one of models.VenueMode's values
    available_modules: Optional[List[str]] = None  # keys from config.MODULE_OPTIONS


# --- Patrons (guest identity -- see models.User) ---

class UserIdentifyRequest(BaseModel):
    # Mirrors DeviceRegisterRequest's pattern: send back the token from a
    # previous visit (localStorage) to keep the same identity across visits.
    token: Optional[str] = None


class UserResponse(BaseModel):
    token: str
    display_name: Optional[str] = None
    avatar: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    avatar: Optional[str] = None


# --- Events ---

class EventCreate(BaseModel):
    title: str
    type: str = "club_night"
    start_at: Optional[datetime] = None  # defaults to now
    end_at: Optional[datetime] = None
    organizer_name: Optional[str] = None
    access_mode: Optional[str] = None  # overrides venue.mode while active
    observer_mode: bool = False
    request_access_allowed: bool = True
    guest_capacity: Optional[int] = None
    scene_props: List[str] = []
    public_visibility: bool = True


class EventUpdate(BaseModel):
    title: Optional[str] = None
    type: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    organizer_name: Optional[str] = None
    access_mode: Optional[str] = None
    observer_mode: Optional[bool] = None
    request_access_allowed: Optional[bool] = None
    guest_capacity: Optional[int] = None
    scene_props: Optional[List[str]] = None
    public_visibility: Optional[bool] = None


class EventResponse(BaseModel):
    id: int
    venue_id: int
    title: str
    type: str
    start_at: datetime
    end_at: Optional[datetime]
    organizer_name: Optional[str]
    access_mode: Optional[str]
    observer_mode: bool
    request_access_allowed: bool
    guest_capacity: Optional[int]
    scene_props: List[str] = []
    public_visibility: bool
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Membership plans & memberships ---

class MembershipPlanCreate(BaseModel):
    name: str
    price: float = 0.0
    interval: str = "monthly"  # monthly | yearly | one_time
    perks: Optional[str] = None
    access_level: str = "members_only"
    qr_access_enabled: bool = True


class MembershipPlanUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    interval: Optional[str] = None
    perks: Optional[str] = None
    access_level: Optional[str] = None
    qr_access_enabled: Optional[bool] = None
    enabled: Optional[bool] = None


class MembershipPlanResponse(BaseModel):
    id: int
    venue_id: int
    name: str
    price: float
    interval: str
    perks: Optional[str]
    access_level: str
    qr_access_enabled: bool
    enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MembershipJoinRequest(BaseModel):
    # No plan_id here on purpose -- POST /membership-plans/{plan_id}/join
    # (guest_router.py) already takes it from the URL path and never reads
    # it off the body; same shape as ProductPurchaseRequest below.
    payment_method: str = "mock_card"


class MembershipResponse(BaseModel):
    id: int
    venue_id: int
    plan_id: int
    status: str
    valid_from: datetime
    valid_to: Optional[datetime]
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


# --- Products ---

class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: float = 0.0
    billing_type: str = "one_time"  # one_time | recurring | included_in_membership
    visibility: bool = True
    grants_entitlements: List[str] = []


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    billing_type: Optional[str] = None
    enabled: Optional[bool] = None
    visibility: Optional[bool] = None
    grants_entitlements: Optional[List[str]] = None


class ProductResponse(BaseModel):
    id: int
    venue_id: int
    name: str
    description: Optional[str]
    price: float
    billing_type: str
    enabled: bool
    visibility: bool
    grants_entitlements: List[str] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductPurchaseRequest(BaseModel):
    payment_method: str = "mock_card"


# --- Access requests ---

class AccessRequestCreate(BaseModel):
    event_id: Optional[int] = None
    note: Optional[str] = None


class AccessRequestDecision(BaseModel):
    approve: bool


class AccessRequestResponse(BaseModel):
    id: int
    venue_id: int
    event_id: Optional[int]
    user_display_name: Optional[str] = None
    note: Optional[str]
    status: str
    created_at: datetime
    decided_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


# --- QR pass & scanner ---

class QrPassResponse(BaseModel):
    token: str
    status: str
    expires_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class QrScanRequest(BaseModel):
    token: str
    event_id: Optional[int] = None


class QrScanResponse(BaseModel):
    result: str  # 'allow' | 'pending' | 'deny'
    reason: str
    user_display_name: Optional[str] = None


# --- Access engine summary (see access_service.py) ---

class AccessSummaryResponse(BaseModel):
    can_view_venue: bool
    can_enter_venue: bool
    can_observe_event: bool
    can_request_access: bool
    can_use_jukebox: bool
    can_show_qr: bool
    can_buy_product: bool
    can_join_membership: bool
    reason: str
    active_event: Optional[EventResponse] = None


# --- Public venue directory / profile ---

class VenueDirectoryItem(BaseModel):
    slug: str
    name: str
    description: Optional[str]
    address: Optional[str]
    scene_theme: str
    mode: str
    active_event: Optional[EventResponse] = None
    available_modules: List[str] = []


class VenuePublicProfile(BaseModel):
    slug: str
    name: str
    description: Optional[str]
    address: Optional[str]
    scene_theme: str
    mode: str
    active_event: Optional[EventResponse] = None
    available_modules: List[str] = []
    membership_plans: List[MembershipPlanResponse] = []
    products: List[ProductResponse] = []
    access: AccessSummaryResponse


# --- NPC dialogue (see dialogue_data.py / dialogue_service.py) ---

class DialogueChoice(BaseModel):
    label: str
    # Present for a real server round-trip (POST .../dialogue/advance); a
    # choice with neither `next` nor `end` set never round-trips server-side.
    next: Optional[str] = None
    end: bool = False
    # Opaque data the client must echo back verbatim in the advance request's
    # `context` when it picks this choice -- e.g. the hacker's queue-item
    # picker stamps {"queue_id": 7} on each dynamically-built choice so the
    # next node knows which song was picked without any server-side session.
    context: dict = {}


class DialogueNodeResponse(BaseModel):
    npc_id: str
    node: str
    speaker: str
    avatar: str
    line: str
    choices: List[DialogueChoice] = []


class DialogueAdvanceRequest(BaseModel):
    # The chosen choice's own `next` + `context` (echoed back verbatim from
    # the DialogueChoice the client just displayed) -- not an index into a
    # re-derived choice list, since action-driven nodes (the hacker's queue
    # picker) build their choices dynamically off live DB state that could
    # have changed between the two requests. `next` only picks *which node
    # to render*; anything trust-sensitive (the hacker's tier, whether a
    # queue_id/tier_id in `context` is real) is always re-verified from the
    # database inside that node's action, never taken on the client's word.
    next: str
    context: dict = {}
