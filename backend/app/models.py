import datetime
import secrets
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.orm import relationship
from backend.app.database import Base
import enum

def _utcnow() -> datetime.datetime:
    # datetime.utcnow() is deprecated (removed in a future Python); this returns
    # an equivalent naive UTC timestamp for the DateTime (non-tz-aware) columns below.
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

class QueueStatus(str, enum.Enum):
    QUEUED = "queued"
    PLAYING = "playing"
    COMPLETED = "completed"
    SKIPPED = "skipped"

class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"

class StyleRule(str, enum.Enum):
    """A venue-defined music style's status, enforced only for Pro venues
    (see style_service.py). PREFERRED is informational (boosts the style in
    the autoplay filler) and doesn't restrict guest requests."""
    PREFERRED = "preferred"
    PREMIUM_ONLY = "premium_only"
    PROHIBITED = "prohibited"

class VenueMode(str, enum.Enum):
    """A venue's (or an active Event's, overriding the venue's) access mode.
    See access_service.py for how this drives what a given guest can do."""
    PUBLIC = "public"
    MEMBERS_ONLY = "members_only"
    PRIVATE_EVENT = "private_event"
    INVITE_ONLY = "invite_only"
    CLOSED = "closed"
    OBSERVER_ALLOWED = "observer_allowed"

class MembershipStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

class AccessRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class QrPassStatus(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"

class Venue(Base):
    """
    A registered bar/venue owner account. Doubles as both the auth principal and
    the tenant record for v1 -- one owner === one venue, no separate Owner/Venue
    split. `slug` is the public identifier used in guest-facing URLs (/v/<slug>)
    and is safe to print on a QR code; `email`/`password_hash` are the login
    credentials and never exposed in API responses.
    """
    __tablename__ = "venues"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(80), nullable=False, unique=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)

    # Simulated billing -- no real payment processor involved, mirrors the
    # existing mock-payment pattern used for guest priority boosts.
    subscription_tier = Column(String(20), nullable=False, default="free")

    # Per-venue media provider state. Previously a single global mutable
    # `settings.ACTIVE_PROVIDER`/`HOST_SPOTIFY_TIER` shared (and clobbered) by
    # every request across the whole app -- now scoped per tenant.
    active_provider = Column(String(20), nullable=False, default="youtube")
    host_spotify_tier = Column(String(20), nullable=False, default="premium")

    # Pro-only knobs (harmless to store for Free venues too -- just unused
    # until they upgrade). See style_service.py / autoplay_service.py.
    premium_style_unlock_fee = Column(Float, nullable=False, default=2.00)
    autoplay_enabled = Column(Boolean, nullable=False, default=False)

    # Owner-set taste profile: which of config.FAVORITE_GENRE_OPTIONS this
    # venue favors. Stored as a comma-separated string of stable `key`s
    # (DB column stays "favorite_genres" for a plain TEXT/VARCHAR migration --
    # see database.py's _LIGHT_MIGRATIONS); the `favorite_genres` property
    # below is what everything else (schemas, autoplay_service) actually
    # reads/writes as a list. Available at every tier, but only has a visible
    # effect once autoplay is running (Pro-only) -- see autoplay_service.py.
    favorite_genres_csv = Column("favorite_genres", Text, nullable=False, default="")

    # Secret behind this venue's copyable, one-click player-linking URL (see
    # venue_router.py's /player-link endpoints and device_service.
    # link_device_via_token) -- opening /play/<slug>/<token> auto-claims a
    # device without the owner having to type a pairing code into the
    # dashboard. Newly registered venues get one immediately (Column
    # default); venues that existed before this feature shipped get '' from
    # the light migration and are lazily backfilled on first use, since a
    # DDL ALTER TABLE default can't call token_urlsafe() per row.
    player_link_token = Column(String(64), nullable=False, default=lambda: secrets.token_urlsafe(24))

    # --- Clubowna: venue-as-community-hub fields (jukebox is now one module
    # among several -- see PLAN.md) ---

    description = Column(Text, nullable=True)
    address = Column(String(255), nullable=True)
    # Placeholder pixel-art preset key (e.g. "pub", "bar", "club", "lounge")
    # the frontend maps to a static tile/sprite set. A full per-venue scene
    # editor is out of scope for MVP -- see PLAN.md section 14.
    scene_theme = Column(String(30), nullable=False, default="pub")

    mode = Column(SQLEnum(VenueMode), nullable=False, default=VenueMode.PUBLIC)

    # Which optional modules (see config.MODULE_OPTIONS) this venue has
    # switched on, e.g. "jukebox,qr_entry". Comma-separated like
    # favorite_genres_csv below -- same reasoning: a plain TEXT column is a
    # trivial light migration, a real many-to-many table isn't worth it yet.
    available_modules_csv = Column("available_modules", Text, nullable=False, default="jukebox,qr_entry")

    created_at = Column(DateTime, default=_utcnow)

    devices = relationship("DeviceLink", back_populates="venue")
    events = relationship("Event", back_populates="venue")
    membership_plans = relationship("MembershipPlan", back_populates="venue")
    products = relationship("Product", back_populates="venue")

    @property
    def favorite_genres(self) -> list:
        return [g for g in (self.favorite_genres_csv or "").split(",") if g]

    @favorite_genres.setter
    def favorite_genres(self, genres) -> None:
        self.favorite_genres_csv = ",".join(genres)

    @property
    def available_modules(self) -> list:
        return [m for m in (self.available_modules_csv or "").split(",") if m]

    @available_modules.setter
    def available_modules(self, modules) -> None:
        self.available_modules_csv = ",".join(modules)

class DeviceLink(Base):
    """
    A physical playback device (the TV/speaker machine at a venue). One row per
    device for its whole lifetime: `device_token` is minted once and persists in
    the player's browser localStorage; `pairing_code` is short-lived and only
    meaningful while `venue_id` is null (unclaimed). Unlinking a device nulls
    `venue_id`/`claimed_at` and mints a fresh code rather than deleting the row,
    so `last_seen_at`/device identity survives an unlink-and-re-pair cycle.
    """
    __tablename__ = "device_links"

    id = Column(Integer, primary_key=True, index=True)
    device_token = Column(String(64), nullable=False, unique=True, index=True)
    pairing_code = Column(String(6), nullable=True, index=True)
    pairing_code_expires_at = Column(DateTime, nullable=True)

    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=True, index=True)
    label = Column(String(120), nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    venue = relationship("Venue", back_populates="devices")

class PriorityTier(Base):
    """Per-venue priority-boost pricing. Seeded with DEFAULT_TIERS (see
    payment_service.py) for each venue at registration time -- there is no
    shared/global tier list anymore."""
    __tablename__ = "priority_tiers"

    id = Column(Integer, primary_key=True, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False, index=True)
    name = Column(String(50), nullable=False)
    cost = Column(Float, nullable=False)
    priority_boost = Column(Integer, nullable=False)
    description = Column(String(255), nullable=True)

class QueueItem(Base):
    __tablename__ = "queue"

    id = Column(Integer, primary_key=True, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False, index=True)
    song_id = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    artist = Column(String(255), nullable=False)
    duration_seconds = Column(Integer, default=180)
    thumbnail_url = Column(Text, nullable=True)
    provider = Column(String(50), default="youtube") # 'youtube', 'spotify'

    # Guest-picked style tag (Pro venues with configured styles only -- see
    # style_service.py). Free-text, matched case-insensitively against the
    # venue's VenueStyle rows.
    style = Column(String(60), nullable=True)
    # True when this row was inserted by the autoplay filler engine rather
    # than an actual guest request -- see autoplay_service.py.
    is_autofilled = Column(Boolean, nullable=False, default=False)

    # Priority sorting score. Base score is timestamp based, increased by paid priority tiers.
    priority_score = Column(Float, default=0.0, index=True)
    status = Column(SQLEnum(QueueStatus), default=QueueStatus.QUEUED, index=True)

    paid_amount = Column(Float, default=0.0)
    created_at = Column(DateTime, default=_utcnow)

    transactions = relationship("Transaction", back_populates="queue_item")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False, index=True)
    queue_id = Column(Integer, ForeignKey("queue.id"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    status = Column(SQLEnum(TransactionStatus), default=TransactionStatus.COMPLETED)
    payment_method = Column(String(50), default="mock_card")
    transaction_reference = Column(String(100), nullable=False)

    # What this payment was for -- 'priority_boost' (queue-bump tiers) or
    # 'style_unlock' (Pro premium-only style fee). See payment_service.py.
    kind = Column(String(20), nullable=False, default="priority_boost")

    # Revenue split snapshot at the time of payment (see
    # payment_service._split_amount). Free venues: venue_amount always 0,
    # app_amount == amount. Pro venues: split per settings.PRO_VENUE_REVENUE_SHARE
    # at the time of the transaction, so later changing the split doesn't
    # retroactively rewrite past transactions.
    venue_amount = Column(Float, nullable=False, default=0.0)
    app_amount = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime, default=_utcnow)

    queue_item = relationship("QueueItem", back_populates="transactions")

class VenueStyle(Base):
    """A venue-defined music style and its enforcement rule (Pro-only
    feature, ignored for Free venues -- see style_service.py)."""
    __tablename__ = "venue_styles"

    id = Column(Integer, primary_key=True, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False, index=True)
    name = Column(String(60), nullable=False)
    rule = Column(SQLEnum(StyleRule), nullable=False, default=StyleRule.PREFERRED)
    created_at = Column(DateTime, default=_utcnow)


# --- Clubowna domain model: patrons, events, membership, access ---
# See PLAN.md section 4. Jukebox above stays exactly as-is; everything below
# is the new "community OS" layer it now lives inside.

class User(Base):
    """
    A patron/guest identity -- deliberately separate from Venue (which is the
    owner/tenant login, see its docstring). No email or password: identity is
    a bearer token minted on first visit and persisted in the browser's
    localStorage, the same pattern DeviceLink already uses for playback
    devices. This lets guests browse and observe anonymously, and only pick a
    display name once they actually need one (holding a membership, sending
    an access request). A full account system (email verification, password
    reset, cross-device login) is deliberately out of scope for MVP -- see
    PLAN.md section 14.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(64), nullable=False, unique=True, index=True)
    display_name = Column(String(80), nullable=True)
    avatar = Column(String(30), nullable=True)  # preset character key, e.g. "avatars_6_char5" (see config.AVATAR_OPTIONS)
    created_at = Column(DateTime, default=_utcnow)

    memberships = relationship("Membership", back_populates="user")
    access_requests = relationship("AccessRequest", back_populates="user")
    qr_passes = relationship("QrPass", back_populates="user")


class Event(Base):
    """A time-boxed happening at a venue (birthday, wedding, club night, ...).
    While active, `access_mode` (if set) overrides the venue's own `mode` --
    see access_service.py."""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False, index=True)
    title = Column(String(150), nullable=False)
    # Free-text (config.EVENT_TYPE_OPTIONS is a soft suggestion list for the
    # admin UI, not a DB-enforced enum) -- birthday/wedding/private_party/
    # club_night/members_session/etc, matching PLAN.md section 4.
    type = Column(String(40), nullable=False, default="club_night")
    start_at = Column(DateTime, nullable=False, default=_utcnow)
    end_at = Column(DateTime, nullable=True)  # null = open-ended/ongoing
    organizer_name = Column(String(120), nullable=True)

    access_mode = Column(SQLEnum(VenueMode), nullable=True)
    observer_mode = Column(Boolean, nullable=False, default=False)
    request_access_allowed = Column(Boolean, nullable=False, default=True)

    guest_capacity = Column(Integer, nullable=True)
    # Pixel-scene prop keys for this event, e.g. "cake,balloons" -- rendered
    # as simple placeholder sprites (see PLAN.md section 17: don't block on
    # final art).
    scene_props_csv = Column("scene_props", Text, nullable=False, default="")
    public_visibility = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=_utcnow)

    venue = relationship("Venue", back_populates="events")
    access_requests = relationship("AccessRequest", back_populates="event")

    @property
    def scene_props(self) -> list:
        return [p for p in (self.scene_props_csv or "").split(",") if p]

    @scene_props.setter
    def scene_props(self, props) -> None:
        self.scene_props_csv = ",".join(props)

    @property
    def is_active(self) -> bool:
        now = _utcnow()
        if self.start_at and now < self.start_at:
            return False
        if self.end_at and now > self.end_at:
            return False
        return True


class MembershipPlan(Base):
    __tablename__ = "membership_plans"

    id = Column(Integer, primary_key=True, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    interval = Column(String(20), nullable=False, default="monthly")  # monthly | yearly | one_time
    perks = Column(Text, nullable=True)
    access_level = Column(SQLEnum(VenueMode), nullable=False, default=VenueMode.MEMBERS_ONLY)
    qr_access_enabled = Column(Boolean, nullable=False, default=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=_utcnow)

    venue = relationship("Venue", back_populates="membership_plans")
    memberships = relationship("Membership", back_populates="plan")


class Membership(Base):
    __tablename__ = "memberships"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("membership_plans.id"), nullable=False, index=True)
    status = Column(SQLEnum(MembershipStatus), nullable=False, default=MembershipStatus.ACTIVE)
    valid_from = Column(DateTime, default=_utcnow)
    valid_to = Column(DateTime, nullable=True)  # null = evergreen until cancelled

    user = relationship("User", back_populates="memberships")
    venue = relationship("Venue")
    plan = relationship("MembershipPlan", back_populates="memberships")

    @property
    def is_active(self) -> bool:
        if self.status != MembershipStatus.ACTIVE:
            return False
        if self.valid_to and _utcnow() > self.valid_to:
            return False
        return True


class Product(Base):
    """A one-off product/service a venue sells (merch, donation, one-time
    entry, ...) outside of a recurring membership."""
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False, default=0.0)
    billing_type = Column(String(20), nullable=False, default="one_time")  # one_time | recurring | included_in_membership
    enabled = Column(Boolean, nullable=False, default=True)
    visibility = Column(Boolean, nullable=False, default=True)
    # Pragmatic simplification (no separate Entitlement table for MVP, see
    # PLAN.md): comma-separated entitlement codes this purchase grants,
    # checked directly by access_service.py -- e.g. "venue_entry,observer".
    grants_entitlements_csv = Column("grants_entitlements", Text, nullable=False, default="")
    created_at = Column(DateTime, default=_utcnow)

    venue = relationship("Venue", back_populates="products")

    @property
    def grants_entitlements(self) -> list:
        return [g for g in (self.grants_entitlements_csv or "").split(",") if g]

    @grants_entitlements.setter
    def grants_entitlements(self, vals) -> None:
        self.grants_entitlements_csv = ",".join(vals)


class AccessRequest(Base):
    """A patron asking a venue's organizer for entry to a members-only /
    private / invite-only venue or event."""
    __tablename__ = "access_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True, index=True)
    note = Column(String(255), nullable=True)
    status = Column(SQLEnum(AccessRequestStatus), nullable=False, default=AccessRequestStatus.PENDING)
    created_at = Column(DateTime, default=_utcnow)
    decided_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="access_requests")
    venue = relationship("Venue")
    event = relationship("Event", back_populates="access_requests")


class QrPass(Base):
    """A patron's venue-entry QR credential. Token-based and opaque by
    design (PLAN.md section 8: "don't put sensitive data in the QR") --
    scanning it just looks up this row and re-runs the access engine."""
    __tablename__ = "qr_passes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False, index=True)
    token = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(SQLEnum(QrPassStatus), nullable=False, default=QrPassStatus.ACTIVE)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", back_populates="qr_passes")
    venue = relationship("Venue")


class Purchase(Base):
    """
    Generic purchase ledger for non-queue payments (memberships, one-off
    products, one-time venue entry). Kept as a separate table from
    Transaction (queue-priority/style-unlock payments, tied to a QueueItem
    via a NOT NULL queue_id) rather than relaxing that column to nullable --
    SQLite can't apply a NOT NULL -> nullable change to an already-existing
    column through the light ADD-COLUMN migrations in database.py, only add
    new columns. Same mock-payment/revenue-split spirit as Transaction; see
    payment_service.py.
    """
    __tablename__ = "purchases"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False, index=True)
    kind = Column(String(30), nullable=False)  # 'membership' | 'product' | 'one_time_entry'
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    membership_plan_id = Column(Integer, ForeignKey("membership_plans.id"), nullable=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)

    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    status = Column(SQLEnum(TransactionStatus), default=TransactionStatus.COMPLETED)
    payment_method = Column(String(50), default="mock_card")
    transaction_reference = Column(String(100), nullable=False)

    # Same revenue-split snapshot pattern as Transaction -- see
    # payment_service._split_amount.
    venue_amount = Column(Float, nullable=False, default=0.0)
    app_amount = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User")
    venue = relationship("Venue")
