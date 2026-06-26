"""App settings - loaded from .env file.

All API keys, URLs, and config options come from here.
Secret: the N2YO key comes from .env, never hardcoded in source.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # N2YO API
    n2yo_api_key: str = Field(default="", description="N2YO API key")
    n2yo_base_url: str = Field(default="https://api.n2yo.com/rest/v1/satellite", description="N2YO API base URL")
    
    # Celestrak
    celestrak_base_url: str = Field(default="https://celestrak.org", description="Celestrak base URL")
    
    # Rate Limiting (stay under N2YO's 1000/hr limit)
    rate_limit_requests_per_hour: int = Field(default=800, description="Max requests per hour (80% of N2YO limit)")
    rate_limit_burst: int = Field(default=10, description="Max burst requests")
    
    # Application
    log_level: str = Field(default="INFO", description="Logging level")
    default_days_ahead: int = Field(default=7, description="Default prediction window in days")
    default_observer_altitude_km: float = Field(default=0.0, description="Default observer altitude in km")
    
    # Timeouts
    http_timeout_seconds: float = Field(default=30.0, description="HTTP request timeout")
    http_max_retries: int = Field(default=3, description="Max retry attempts")
    http_backoff_factor: float = Field(default=1.0, description="Exponential backoff factor")
    
    @property
    def has_n2yo_key(self) -> bool:
        """Check if N2YO API key is configured."""
        return bool(self.n2yo_api_key and self.n2yo_api_key != "your_n2yo_api_key_here")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def load_env_file(env_path: Optional[Path] = None) -> None:
    """Explicitly load .env file if needed."""
    if env_path and env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path, override=True)
    else:
        from dotenv import load_dotenv
        load_dotenv(override=True)