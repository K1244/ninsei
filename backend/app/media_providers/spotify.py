from typing import List, Dict, Any
from backend.app.media_providers.base import BaseMediaProvider, SpotifyPremiumRequiredException
from backend.app.schemas import TrackSearchResult

DEMO_SPOTIFY_TRACKS = [
    TrackSearchResult(
        song_id="spotify:track:4cOdK2wGLETKBW3PvgPWqT",
        title="Never Gonna Give You Up (Spotify)",
        artist="Rick Astley",
        duration_seconds=213,
        thumbnail_url="https://i.scdn.co/image/ab67616d0000b273b75416f4618e474582f34731",
        provider="spotify"
    ),
    TrackSearchResult(
        song_id="spotify:track:0VjljfeZiyKuDvw1y6ko87",
        title="Flowers",
        artist="Miley Cyrus",
        duration_seconds=200,
        thumbnail_url="https://i.scdn.co/image/ab67616d0000b273f429549123d928a42b1095d3",
        provider="spotify"
    )
]

class SpotifyProvider(BaseMediaProvider):
    """
    Stubbed Spotify Media Provider strategy demonstrating how Spotify Web Playback SDK
    will be integrated into the architecture. Handles Premium verification & 403 Forbidden scenarios.
    """

    @property
    def provider_name(self) -> str:
        return "spotify"

    async def search_tracks(self, query: str, limit: int = 10) -> List[TrackSearchResult]:
        q_lower = query.lower()
        matched = [
            t for t in DEMO_SPOTIFY_TRACKS
            if q_lower in t.title.lower() or q_lower in t.artist.lower()
        ]
        return matched if matched else DEMO_SPOTIFY_TRACKS[:limit]

    async def get_track_details(self, song_id: str) -> TrackSearchResult:
        for t in DEMO_SPOTIFY_TRACKS:
            if t.song_id == song_id:
                return t
        return TrackSearchResult(
            song_id=song_id,
            title=f"Spotify Track ({song_id})",
            artist="Spotify Artist",
            duration_seconds=200,
            thumbnail_url="https://i.scdn.co/image/ab67616d0000b273b75416f4618e474582f34731",
            provider="spotify"
        )

    async def validate_host_account(self, host_tier: str) -> Dict[str, Any]:
        """
        Validates host Spotify account tier.
        The Spotify Web Playback SDK strictly requires a Spotify Premium account.
        If host_tier is 'free' or subscription has lapsed, throws SpotifyPremiumRequiredException (403).
        """
        if host_tier.lower() != "premium":
            raise SpotifyPremiumRequiredException(
                "Host Spotify account tier is 'Free'. Spotify Web Playback SDK requires an active Premium subscription (HTTP 403 Forbidden)."
            )
            
        return {
            "valid": True,
            "provider": "spotify",
            "tier": "premium",
            "can_play": True,
            "message": "Spotify Web Playback SDK authenticated. Host Premium active."
        }
