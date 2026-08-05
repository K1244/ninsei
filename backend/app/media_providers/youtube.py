import httpx
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

class YouTubeProvider(BaseMediaProvider):
    """YouTube Media Provider strategy implementation using YouTube Data API & fallback mock catalog."""

    @property
    def provider_name(self) -> str:
        return "youtube"

    async def search_tracks(self, query: str, limit: int = 10) -> List[TrackSearchResult]:
        if settings.YOUTUBE_API_KEY:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/search",
                        params={
                            "part": "snippet",
                            "q": f"{query} music video",
                            "type": "video",
                            "videoCategoryId": "10",
                            "maxResults": limit,
                            "key": settings.YOUTUBE_API_KEY
                        },
                        timeout=5.0
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        results = []
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
                print(f"[YouTubeProvider] API search failed, falling back to local dataset: {e}")

        # Local search filtering
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
        # YouTube supports ad-supported free account playback seamlessly
        return {
            "valid": True,
            "provider": "youtube",
            "tier": host_tier,
            "can_play": True,
            "message": "YouTube playback active. Standard audio/video stream available."
        }
