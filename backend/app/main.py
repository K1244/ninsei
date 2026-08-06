import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.app.config import settings
from backend.app.database import init_db, AsyncSessionLocal
from backend.app.routers import ws_router, auth_router, device_router, venue_router, guest_router

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
    return FileResponse(os.path.join(FRONTEND_DIR, "landing.html"))

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

@app.get("/v/{slug}", response_class=FileResponse)
async def guest_page(slug: str):
    # Same static file for every venue -- the slug is read and validated
    # client-side (see jukebox.js), which calls /api/v/{slug}/meta to confirm
    # it's real and shows a "venue not found" state otherwise.
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
