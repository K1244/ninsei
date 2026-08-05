from abc import ABC, abstractmethod
from typing import List, Dict, Any
from backend.app.schemas import TrackSearchResult

class SpotifyPremiumRequiredException(Exception):
    """Raised when host Spotify account lacks Premium subscription required for Web Playback SDK."""
    def __init__(self, message: str = "Host Spotify Premium subscription lapsed. Web Playback SDK 403 Forbidden."):
        self.message = message
        self.status_code = 403
        super().__init__(self.message)

class BaseMediaProvider(ABC):
    """Abstract Base Class (Strategy Interface) for Media Playback & Search Providers."""
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Returns provider identifier string (e.g. 'youtube', 'spotify')."""
        pass

    @abstractmethod
    async def search_tracks(self, query: str, limit: int = 10) -> List[TrackSearchResult]:
        """Search tracks for the given query string."""
        pass

    @abstractmethod
    async def get_track_details(self, song_id: str) -> TrackSearchResult:
        """Fetch details for a specific song ID."""
        pass

    @abstractmethod
    async def validate_host_account(self, host_tier: str) -> Dict[str, Any]:
        """Validates host account status. Raises exception or returns status dictionary."""
        pass
