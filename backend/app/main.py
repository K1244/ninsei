import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.app.config import settings
from backend.app.database import init_db, AsyncSessionLocal
from backend.app.routers import api_router, ws_router
from backend.app.services.payment_service import seed_priority_tiers

@asynccontextmanager
async def lifespan(app: FastAPI):
    # App startup
    print(f"Starting {settings.APP_NAME}...")
    await init_db()
    async with AsyncSessionLocal() as session:
        await seed_priority_tiers(session)
    yield
    # App shutdown
    print("Shutting down Jukebox application...")

app = FastAPI(
    title=settings.APP_NAME,
    description="Virtual Jukebox & Request Machine API with YouTube IFrame API & Spotify Adapter Pattern",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for local dev and remote clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API and WebSocket routers
app.include_router(api_router.router)
app.include_router(ws_router.router)

# Base directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# HTML Page Routes
@app.get("/", response_class=FileResponse)
async def jukebox_home():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/player", response_class=FileResponse)
async def playback_client():
    return FileResponse(os.path.join(FRONTEND_DIR, "player.html"))

@app.get("/admin", response_class=FileResponse)
async def admin_dashboard():
    return FileResponse(os.path.join(FRONTEND_DIR, "admin.html"))
