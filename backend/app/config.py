import os
from pydantic_settings import BaseSettings

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

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
