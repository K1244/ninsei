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

# Optional modules a venue owner can switch on/off in the admin dashboard
# (see venue_router.py, Venue.available_modules in models.py, and PLAN.md
# section 7). "jukebox" is the module this app started as -- now just one of
# several. New venues default to Venue.available_modules_csv's column
# default ("jukebox,qr_entry"); the rest are opt-in.
MODULE_OPTIONS = [
    {"key": "jukebox", "label": "Jukebox"},
    {"key": "observers", "label": "Observers"},
    {"key": "request_access", "label": "Request Access"},
    {"key": "qr_entry", "label": "QR Entry"},
    {"key": "screen_messages", "label": "Screen Messages"},
    {"key": "products", "label": "Products"},
    {"key": "memberships", "label": "Memberships"},
    {"key": "donations", "label": "Donations / Support"},
    {"key": "merch", "label": "Merch"},
    {"key": "lounge_access", "label": "Lounge Access"},
    {"key": "one_time_entry", "label": "One-time Entry"},
]
MODULE_KEYS = {m["key"] for m in MODULE_OPTIONS}
MODULE_LABELS = {m["key"]: m["label"] for m in MODULE_OPTIONS}

# Soft suggestion list for the "type" field on an Event -- stored as plain
# text (models.Event.type), not a DB-enforced enum, so an owner can still
# type a custom one. Purely for the admin UI's dropdown.
EVENT_TYPE_OPTIONS = [
    {"key": "club_night", "label": "Club Night"},
    {"key": "members_session", "label": "Members Session"},
    {"key": "birthday", "label": "Birthday Party"},
    {"key": "wedding", "label": "Wedding"},
    {"key": "private_party", "label": "Private Party"},
]

# Pixel-art scene theme presets a venue can pick for its scene (see
# Venue.scene_theme) -- the frontend maps each key to a static tile/sprite
# set. Placeholder graphics only for MVP, see PLAN.md section 17.
SCENE_THEME_OPTIONS = [
    {"key": "pub", "label": "Pub"},
    {"key": "bar", "label": "Bar"},
    {"key": "club", "label": "Club"},
    {"key": "lounge", "label": "Lounge"},
]

# --- Pixel-art asset catalog ---
# The raw reference sheets a human dropped into the repo (see PLAN.md
# section 17) got cut into individual transparent-background sprites by
# tools/slice_sprites.py, indexed in frontend/static/assets/sprites/manifest.json.
# Loaded once here so config.py stays the single place other modules pull
# asset options from -- same pattern as FAVORITE_GENRE_OPTIONS/MODULE_OPTIONS
# above, just sourced from that manifest instead of being hand-typed.
#
# Falls back to an empty catalog (never raises) if the manifest is missing --
# e.g. a checkout of the repo without frontend/static/assets/ populated
# shouldn't crash the whole app over avatar options.
import json as _json

_ASSETS_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend", "static", "assets", "sprites",
)


def _load_sprite_manifest() -> list:
    try:
        with open(os.path.join(_ASSETS_ROOT, "manifest.json")) as f:
            return _json.load(f)
    except (OSError, ValueError):
        return []


_SPRITE_MANIFEST = _load_sprite_manifest()
_SPRITES_BY_CATEGORY: dict = {}
for _entry in _SPRITE_MANIFEST:
    _SPRITES_BY_CATEGORY.setdefault(_entry["file"].split("/", 1)[0], []).append(_entry)

# User.avatar preset options (see models.User's docstring / patron_router.py's
# GET /api/users/avatar-options). Sourced from characters.json, not straight
# off manifest.json -- the raw manifest has one entry per individually cut
# sprite cell, and several of those are the same character from a different
# angle (front/back/side) or a different walk-cycle frame; tools/
# curate_characters.py groups those back into characters (see its docstring
# for how, and PLAN.md/chat history for why that needs to be a color-
# similarity clustering pass rather than a fixed row/col rule -- the 6 source
# sheets don't share one column-per-character convention). `key` is what's
# stored on User.avatar (fits its String(30) column); `thumbnail` is a single
# representative frame for the picker grid; `frames` is every pose/animation
# frame for that character, in display order, for the room/venue scene to
# cycle through while the character walks.
def _load_character_manifest() -> list:
    try:
        with open(os.path.join(_ASSETS_ROOT, "characters.json")) as f:
            return _json.load(f)
    except (OSError, ValueError):
        return []


_CHARACTER_MANIFEST = _load_character_manifest()
# Most-to-least frames = best-to-worst animated: frame count is the only
# honest, fully-automatic signal available here for "how much this character
# actually moves" (see curate_characters.py's docstring -- there's no
# reliable per-frame front/back/walk-cycle label to sort on instead). It's
# not a perfect proxy -- a character with several near-duplicate reference
# poses can outrank one with fewer but genuinely animated walk-cycle frames
# -- but it puts the sheets that actually have real walk cycles
# (avatars_6.png, part of avatars_5.png) at/near the top, and a picker that's
# ordered by "how alive does this look" beats key-alphabetical either way.
AVATAR_OPTIONS = [
    {
        "key": _c["key"],
        "thumbnail": f"assets/sprites/{_c['thumbnail']}",
        "frames": [f"assets/sprites/{_f}" for _f in _c["frames"]],
    }
    for _c in sorted(_CHARACTER_MANIFEST, key=lambda c: (-len(c["frames"]), c["key"]))
]
AVATAR_KEYS = {a["key"] for a in AVATAR_OPTIONS}
AVATAR_FRAMES_BY_KEY = {a["key"]: a["frames"] for a in AVATAR_OPTIONS}

# Event.scene_props sprite lookup (see models.Event.scene_props / seed_demo.py's
# "cake,balloons" / "wedding_decor,flowers"). Hand-picked from props/items*.png
# rather than auto-generated like AVATAR_OPTIONS -- scene props are placed by
# meaning ("this event has a cake"), not browsed like an avatar grid, so each
# key needs an actual human-chosen sprite rather than every cut prop getting
# an auto key. Extend as more events need more prop keys; the rest of
# props/'s cut sprites are all still on disk either way.
SCENE_PROP_SPRITES = {
    "balloons": "assets/sprites/props/items_r0_c0.png",
    "gifts": "assets/sprites/props/items_r0_c1.png",
    "flowers": "assets/sprites/props/items_r0_c2.png",
    "wedding_decor": "assets/sprites/props/items_r0_c3.png",
    "champagne": "assets/sprites/props/items_r0_c4.png",
    "candles": "assets/sprites/props/items_r0_c5.png",
    "disco_ball": "assets/sprites/props/items_r1_c0.png",
    "cake": "assets/sprites/props/items_r1_c1.png",
    "neon_heart": "assets/sprites/props/items_r1_c2.png",
    "palm_plant": "assets/sprites/props/items_r1_c3.png",
    "arcade_cabinet": "assets/sprites/props/items_r1_c4.png",
}

# Venue.scene_theme -> which cut venue-tile sheet(s) (venue/ sprites, see
# PLAN.md section 3) the not-yet-built scene renderer should draw floor/wall
# tiles and furniture from. "pub" and "bar" share the same warm wood-and-brass
# set for now (no dedicated "pub" sheet was generated); "club" and "lounge"
# each have their own.
SCENE_THEME_SOURCE_SHEETS = {
    "pub": ["venue_bar_items.png", "venue_bar_tools.png"],
    "bar": ["venue_bar_items.png", "venue_bar_tools.png"],
    "club": ["venue_club_tools.png"],
    "lounge": ["venue_underground.png"],
}
