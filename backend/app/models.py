import datetime
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

    created_at = Column(DateTime, default=_utcnow)

    devices = relationship("DeviceLink", back_populates="venue")

    @property
    def favorite_genres(self) -> list:
        return [g for g in (self.favorite_genres_csv or "").split(",") if g]

    @favorite_genres.setter
    def favorite_genres(self, genres) -> None:
        self.favorite_genres_csv = ",".join(genres)

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
