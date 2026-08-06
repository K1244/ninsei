import httpx
import random
from typing import List, Dict, Any
from backend.app.media_providers.base import BaseMediaProvider
from backend.app.schemas import TrackSearchResult
from backend.app.config import settings

# Built-in fallback database of popular music tracks with real working YouTube IDs
DEMO_YOUTUBE_TRACKS = [
    TrackSearchResult(
        song_id="dQw4w9WgXcQ",
        title="Never Gonna Give You Up",
        artist="Rick Astley",
        duration_seconds=212,
        thumbnail_url="https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        provider="youtube"
    ),
    TrackSearchResult(
        song_id="fJ9rUzIMcZQ",
        title="Bohemian Rhapsody",
        artist="Queen",
        duration_seconds=355,
        thumbnail_url="https://img.youtube.com/vi/fJ9rUzIMcZQ/hqdefault.jpg",
        provider="youtube"
    ),
    TrackSearchResult(
        song_id="OPf0YbXqDm0",
        title="Uptown Funk",
        artist="Mark Ronson ft. Bruno Mars",
        duration_seconds=270,
        thumbnail_url="https://img.youtube.com/vi/OPf0YbXqDm0/hqdefault.jpg",
        provider="youtube"
    ),
    TrackSearchResult(
        song_id="09R8_2nJtjg",
        title="Sugar",
        artist="Maroon 5",
        duration_seconds=235,
        thumbnail_url="https://img.youtube.com/vi/09R8_2nJtjg/hqdefault.jpg",
        provider="youtube"
    ),
    TrackSearchResult(
        song_id="kJQP7kiw5Fk",
        title="Despacito",
        artist="Luis Fonsi ft. Daddy Yankee",
        duration_seconds=228,
        thumbnail_url="https://img.youtube.com/vi/kJQP7kiw5Fk/hqdefault.jpg",
        provider="youtube"
    ),
    TrackSearchResult(
        song_id="JGwWNGJdvx8",
        title="Shape of You",
        artist="Ed Sheeran",
        duration_seconds=234,
        thumbnail_url="https://img.youtube.com/vi/JGwWNGJdvx8/hqdefault.jpg",
        provider="youtube"
    ),
    TrackSearchResult(
        song_id="hT_nvWreIhg",
        title="Counting Stars",
        artist="OneRepublic",
        duration_seconds=257,
        thumbnail_url="https://img.youtube.com/vi/hT_nvWreIhg/hqdefault.jpg",
        provider="youtube"
    ),
    TrackSearchResult(
        song_id="4NRXx6U8ABQ",
        title="Blinding Lights",
        artist="The Weeknd",
        duration_seconds=200,
        thumbnail_url="https://img.youtube.com/vi/4NRXx6U8ABQ/hqdefault.jpg",
        provider="youtube"
    )
]

# List of public open API mirrors for keyless YouTube / Music search
INVIDIOUS_INSTANCES = [
    "https://inv.tux.pizza",
    "https://invidious.nerdvpn.de",
    "https://invidious.drgns.space"
]

class YouTubeProvider(BaseMediaProvider):
    """
    Multi-Source Music Search Provider Strategy.
    Aggregates results from multiple sources automatically:
    1. Official YouTube Data API v3 (if key configured)
    2. Public Invidious Open Search API (No API key required)
    3. iTunes Search API (No API key required)
    4. Offline high-quality fallback catalog
    """

    @property
    def provider_name(self) -> str:
        return "youtube"

    async def search_tracks(self, query: str, limit: int = 10) -> List[TrackSearchResult]:
        results: List[TrackSearchResult] = []

        # Source 1: Official YouTube Data API (if key exists)
        if settings.YOUTUBE_API_KEY:
            try:
                # Support comma-separated API keys pool with rotation
                api_keys = [k.strip() for k in settings.YOUTUBE_API_KEY.split(",") if k.strip()]
                selected_key = random.choice(api_keys) if api_keys else settings.YOUTUBE_API_KEY
                
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/search",
                        params={
                            "part": "snippet",
                            "q": f"{query} music video",
                            "type": "video",
                            "videoCategoryId": "10",
                            "maxResults": limit,
                            "key": selected_key
                        },
                        timeout=4.0
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for item in data.get("items", []):
                            video_id = item["id"]["videoId"]
                            snippet = item["snippet"]
                            results.append(
                                TrackSearchResult(
                                    song_id=video_id,
                                    title=snippet["title"],
                                    artist=snippet["channelTitle"],
                                    duration_seconds=210,
                                    thumbnail_url=snippet["thumbnails"]["medium"]["url"],
                                    provider="youtube"
                                )
                            )
                        if results:
                            return results
            except Exception as e:
                print(f"[MultiSourceSearch] YouTube API search bypassed: {e}")

        # Source 2: Public Invidious Mirror Search (Keyless)
        for instance in INVIDIOUS_INSTANCES:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{instance}/api/v1/search",
                        params={"q": query, "type": "video"},
                        timeout=3.0
                    )
                    if resp.status_code == 200:
                        items = resp.json()
                        for item in items[:limit]:
                            if "videoId" in item:
                                results.append(
                                    TrackSearchResult(
                                        song_id=item["videoId"],
                                        title=item.get("title", "Unknown Track"),
                                        artist=item.get("author", "YouTube Channel"),
                                        duration_seconds=item.get("lengthSeconds", 180),
                                        thumbnail_url=f"https://img.youtube.com/vi/{item['videoId']}/hqdefault.jpg",
                                        provider="youtube"
                                    )
                                )
                        if results:
                            return results
            except Exception:
                continue

        # Source 3: iTunes Public Music API (Keyless fallback with real YouTube ID matching)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://itunes.apple.com/search",
                    params={"term": query, "entity": "song", "limit": limit},
                    timeout=3.0
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("results", []):
                        track_name_lower = item["trackName"].lower()
                        # Only surface an iTunes result when we can pair it with a YouTube
                        # ID we're confident is the *same* song. Previously, unmatched
                        # tracks fell back to an arbitrary demo video by index, which
                        # displayed correct metadata (title/artist/art) for a completely
                        # different song than what actually played. Skip rather than guess.
                        matching_demo = next(
                            (d for d in DEMO_YOUTUBE_TRACKS
                             if track_name_lower in d.title.lower() or d.title.lower() in track_name_lower),
                            None
                        )
                        if not matching_demo:
                            continue
                        results.append(
                            TrackSearchResult(
                                song_id=matching_demo.song_id,
                                title=item["trackName"],
                                artist=item["artistName"],
                                duration_seconds=int(item.get("trackTimeMillis", 180000) / 1000),
                                thumbnail_url=item.get("artworkUrl100", matching_demo.thumbnail_url),
                                provider="youtube"
                            )
                        )
                    if results:
                        return results
        except Exception as e:
            print(f"[MultiSourceSearch] iTunes search fallback error: {e}")

        # Source 4: Local catalog matching
        q_lower = query.lower()
        matched = [
            t for t in DEMO_YOUTUBE_TRACKS
            if q_lower in t.title.lower() or q_lower in t.artist.lower()
        ]
        return matched if matched else DEMO_YOUTUBE_TRACKS[:limit]

    async def get_track_details(self, song_id: str) -> TrackSearchResult:
        for t in DEMO_YOUTUBE_TRACKS:
            if t.song_id == song_id:
                return t
        return TrackSearchResult(
            song_id=song_id,
            title=f"YouTube Track ({song_id})",
            artist="Unknown Artist",
            duration_seconds=180,
            thumbnail_url=f"https://img.youtube.com/vi/{song_id}/hqdefault.jpg",
            provider="youtube"
        )

    async def validate_host_account(self, host_tier: str) -> Dict[str, Any]:
        return {
            "valid": True,
            "provider": "youtube",
            "tier": host_tier,
            "can_play": True,
            "message": "Multi-Source search & playback active. Ad-supported / open stream available."
        }
