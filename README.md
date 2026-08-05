# Virtual Jukebox & Request Machine

A full-stack real-time Virtual Jukebox web application. Users can browse, search, and request songs to a central queue, pay simulated fees to bump priority order, and stream playback continuously on a connected TV or audio system using the YouTube IFrame API.

---

## 🌟 Key Features

1. **User Jukebox (`/`)**: Mobile-first UI for guests to search songs, add tracks to the queue, view currently playing music, and simulate priority payment bumps ($1.00 to $5.00) with instant re-ordering.
2. **Dedicated Playback Client (`/player`)**: Continuous browser window meant for TV/Speaker host setup. Embeds the YouTube IFrame API, auto-plays queued tracks, synced progress control, and auto-advances the queue when songs finish.
3. **Admin Dashboard (`/admin`)**: Moderate queue, skip tracks, clear queue, and simulate host subscription statuses (e.g. testing Spotify Premium lapsed 403 error alerts).
4. **Media Strategy / Adapter Pattern**: Clean abstract media provider interface (`BaseMediaProvider`), featuring active `YouTubeProvider` and extensible `SpotifyProvider` with Web Playback SDK status checks.
5. **Zerops PaaS Ready**: Includes complete `zerops.yml` setup for FastAPI, PostgreSQL, and Redis.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy (Async), Pydantic v2
- **Database**: PostgreSQL (Production) / SQLite (Async zero-config local fallback) + Redis
- **Frontend**: Modern Vanilla JS + HTML5 + CSS3 (Glassmorphism & Micro-animations)
- **Playback Engine**: YouTube Data API v3 & YouTube IFrame API
- **Deployment**: Zerops PaaS (`zerops.yml`)

---

## 🚀 Local Quickstart

### 1. Install Dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 2. Launch FastAPI App
```bash
python3 -m uvicorn backend.app.main:app --reload --port 8000
```

### 3. Access Pages
- **User Mobile Jukebox**: `http://localhost:8000/`
- **Playback Client (TV/Stage)**: `http://localhost:8000/player`
- **Admin Dashboard**: `http://localhost:8000/admin`

---

## ☁️ Deployment on Zerops PaaS

The application is fully configured for deployment on Zerops PaaS using the included `zerops.yml` file.

1. Create a project on Zerops.
2. Import repository or push via Zerops CLI (`zcli`).
3. Zerops automatically provisions the Python FastAPI service, PostgreSQL database, and Redis cache.
