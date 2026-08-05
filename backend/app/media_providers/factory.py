from backend.app.media_providers.base import BaseMediaProvider
from backend.app.media_providers.youtube import YouTubeProvider
from backend.app.media_providers.spotify import SpotifyProvider
from backend.app.config import settings

class MediaProviderFactory:
    _providers = {
        "youtube": YouTubeProvider(),
        "spotify": SpotifyProvider()
    }

    @classmethod
    def get_provider(cls, name: str = None) -> BaseMediaProvider:
        provider_name = name or settings.ACTIVE_PROVIDER
        provider = cls._providers.get(provider_name.lower())
        if not provider:
            raise ValueError(f"Unknown media provider '{provider_name}'. Supported: {list(cls._providers.keys())}")
        return provider
