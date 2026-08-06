import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.app.config import settings
from backend.app.database import init_db, AsyncSessionLocal
from backend.app.routers import (
    ws_router, auth_router, device_router, venue_router, guest_router,
    directory_router, patron_router,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # App startup
    if not settings.SECRET_KEY:
        # Session cookies are signed with this key -- booting with it empty would
        # mean either a crash-on-first-use later or (worse) a predictable/blank
        # key silently signing every venue's session. Fail loudly at startup
        # instead.
        raise RuntimeError(
            "SECRET_KEY is not set. Generate one (e.g. `python -c \"import secrets; "
            "print(secrets.token_hex(32))\"`) and set it via the SECRET_KEY env var."
        )
    print(f"Starting {settings.APP_NAME}...")
    await init_db()
    # Priority tiers are seeded per-venue at registration time now (see
    # auth_router.py) rather than once globally -- nothing to seed at startup.
    yield
    # App shutdown
    print("Shutting down Jukebox application...")

app = FastAPI(
    title=settings.APP_NAME,
    description="Virtual Jukebox & Request Machine API with YouTube IFrame API & Spotify Adapter Pattern",
    version="1.0.1",
    lifespan=lifespan
)

# Enable CORS. Every page (landing/dashboard/guest/player) is served by this
# same FastAPI process at one origin -- there is no separate frontend host --
# so dashboard cookie auth works same-origin without needing a CORS credentials
# exception at all. PUBLIC_ORIGIN pins that one real origin in production; when
# it's unset (local dev), fall back to the permissive/credential-less wildcard
# that was already in place before auth existed.
if settings.PUBLIC_ORIGIN:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.PUBLIC_ORIGIN, "http://localhost:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Include API and WebSocket routers
app.include_router(auth_router.router)
app.include_router(device_router.router)
app.include_router(venue_router.router)
app.include_router(guest_router.router)
app.include_router(directory_router.router)
app.include_router(patron_router.router)
app.include_router(ws_router.router)

# Base directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# HTML Page Routes
@app.get("/", response_class=FileResponse)
async def landing_page():
    # PLAN.md section 2 is explicit: the landing page *is* the pixelart room,
    # not a separate marketing splash -- same file /room serves. The old
    # marketing landing.html is unreferenced now (kept on disk, unlinked)
    # rather than deleted, in case it's wanted again later.
    return FileResponse(os.path.join(FRONTEND_DIR, "room.html"))

@app.get("/register", response_class=FileResponse)
async def register_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "register.html"))

@app.get("/login", response_class=FileResponse)
async def login_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))

@app.get("/dashboard", response_class=FileResponse)
async def dashboard_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "dashboard.html"))

@app.get("/play", response_class=FileResponse)
async def play_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "play.html"))

@app.get("/play/{slug}/{token}", response_class=FileResponse)
async def play_page_direct_link(slug: str, token: str):
    # Same static file as the generic /play above -- slug/token are read and
    # verified client-side (see play.js's tryAutoLinkFromUrl, which posts
    # them to /api/devices/link) so this device auto-claims itself against
    # that venue with no pairing code entry needed. See venue_router.py's
    # /player-link, which is where this URL is generated for the dashboard.
    return FileResponse(os.path.join(FRONTEND_DIR, "play.html"))

@app.get("/v/{slug}", response_class=FileResponse)
async def guest_page(slug: str):
    # Same static file for every venue -- the slug is read and validated
    # client-side (see jukebox.js), which calls /api/v/{slug}/meta to confirm
    # it's real and shows a "venue not found" state otherwise.
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

# --- Clubowna pixelart patron-facing pages (PLAN.md sections 2/3/6/10) ---

@app.get("/room", response_class=FileResponse)
async def room_page():
    # The pixelart landing scene -- a patron's entry point into Clubowna,
    # separate from "/" (the venue-owner marketing/signup page above, kept
    # as-is per PLAN.md's "keep the working parts" instruction).
    return FileResponse(os.path.join(FRONTEND_DIR, "room.html"))

@app.get("/venues", response_class=FileResponse)
async def venues_page():
    # The venue hub/directory (PLAN.md section 6) -- venues.js pulls the
    # actual list from GET /api/venues (directory_router.py).
    return FileResponse(os.path.join(FRONTEND_DIR, "venues.html"))

@app.get("/venue/{slug}", response_class=FileResponse)
async def venue_scene_page(slug: str):
    # The pixelart venue scene (PLAN.md section 3) -- distinct from /v/{slug}
    # above, which is the existing plain guest jukebox request page. venue.js
    # reads the slug client-side and drives everything off
    # GET /api/venues/{slug} + GET /api/v/{slug}/access.
    return FileResponse(os.path.join(FRONTEND_DIR, "venue.html"))
