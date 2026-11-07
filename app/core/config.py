from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    DATABASE_URL: str = "sqlite+aiosqlite:///./data.db"
    TRAKT_CLIENT_ID: str = ""
    TRAKT_CLIENT_SECRET: str = ""
    TRAKT_REDIRECT_URI: str = "http://localhost:8000/auth/trakt/callback"
    TMDB_API_KEY: str = ""
    SECRET_KEY: str = "kKkXb7x9xY7b2pP0lM8sD5eE2rR4tT6yU8iO0pA2sD4="
    
    SYNC_INTERVAL_MINUTES: int = 15
    LETTERBOXD_USERNAME: str = ""
    
    # Directory paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    EXPORTS_DIR: Path = BASE_DIR / "exports"
    UPLOADS_DIR: Path = BASE_DIR / "uploads"


settings = Settings()
settings.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
