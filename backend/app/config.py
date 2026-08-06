import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    APP_NAME: str = "Virtual Jukebox API"
    DEBUG: bool = True
    
    # Database
    # Default to a local SQLite database if DATABASE_URL is not set or SQLite is requested
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./jukebox.db")
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    USE_REDIS: bool = False
    
    # Media Providers Config
    YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "")
    ACTIVE_PROVIDER: str = "youtube" # 'youtube' or 'spotify'
    
    # Host Account Subscription Status (Simulated)
    # 'premium' vs 'free'
    HOST_SPOTIFY_TIER: str = os.getenv("HOST_SPOTIFY_TIER", "premium")

    # Pro-tier revenue split: fraction of guest payment revenue (priority
    # boosts + style-unlock fees) a Pro venue keeps; the app keeps the rest.
    # Free venues always keep 0% -- 100% of their revenue goes to the app,
    # same as today. Fixed platform-wide split for now (not per-venue).
    PRO_VENUE_REVENUE_SHARE: float = float(os.getenv("PRO_VENUE_REVENUE_SHARE", "0.70"))

    # Autoplay filler engine (Pro-only, see autoplay_service.py): trigger
    # a top-up when fewer than this many real requests are still QUEUED,
    # and avoid repeating an artist within this many recent tracks.
    AUTOPLAY_FILL_THRESHOLD: int = int(os.getenv("AUTOPLAY_FILL_THRESHOLD", "2"))
    AUTOPLAY_NO_REPEAT_ARTIST_WINDOW: int = int(os.getenv("AUTOPLAY_NO_REPEAT_ARTIST_WINDOW", "2"))

    # Auth
    # Signs/verifies venue owner session cookies (itsdangerous). Required --
    # main.py's startup check refuses to boot with this empty rather than
    # silently running session auth on a blank/predictable key.
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")

    # The single public origin this app is actually served from (e.g.
    # "https://app-2a04-8000.prg1.zerops.app"). Used to scope CORS and decide
    # whether session cookies should require HTTPS. Left empty for local dev,
    # where CORS falls back to the permissive/credential-less wildcard below.
    PUBLIC_ORIGIN: str = os.getenv("PUBLIC_ORIGIN", "")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

# Fixed checklist of genres a venue owner can mark as favorites in their
# profile (see venue_router.py / dashboard.js). A stable `key` is what's
# actually stored on Venue.favorite_genres and compared against in
# autoplay_service.py; `label` is just the checkbox's display text -- kept
# separate so relabeling one later doesn't silently break stored data.
FAVORITE_GENRE_OPTIONS = [
    {"key": "pop", "label": "Pop"},
    {"key": "rock", "label": "Rock"},
    {"key": "hip_hop", "label": "Hip-Hop / Rap"},
    {"key": "electronic", "label": "Electronic / Dance"},
    {"key": "rnb", "label": "R&B / Soul"},
    {"key": "country", "label": "Country"},
    {"key": "latin", "label": "Latin"},
    {"key": "jazz", "label": "Jazz"},
    {"key": "classical", "label": "Classical"},
    {"key": "metal", "label": "Metal"},
    {"key": "indie", "label": "Indie / Alternative"},
    {"key": "reggae", "label": "Reggae"},
]
FAVORITE_GENRE_KEYS = {g["key"] for g in FAVORITE_GENRE_OPTIONS}
FAVORITE_GENRE_LABELS = {g["key"]: g["label"] for g in FAVORITE_GENRE_OPTIONS}
