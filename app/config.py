"""Application configuration loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MongoDB
    mongo_uri: str
    db_name: str = ""  # derived from URI path when empty

    # HTTP / CORS
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = (
        "http://localhost:8080,http://localhost:5173,"
        "http://127.0.0.1:8080,http://127.0.0.1:5173"
    )

    # Live simulator (generates fresh sensor readings so the dashboard is live)
    simulator_enabled: bool = True
    simulator_interval_seconds: float = 5.0

    # Alert identity
    alert_sender: str = "floodwatch@unilag.edu.ng"

    # Shared-secret auth for hardware device ingestion (POST /api/v1/readings).
    # Comma-separated list: one key for the whole fleet, or a few keys so a
    # single compromised unit can be revoked without rotating everyone else.
    # Empty (default) disables the check, for local/dev use before devices
    # are provisioned with a real key.
    device_api_keys: str = ""

    @property
    def device_api_key_set(self) -> set[str]:
        return {k.strip() for k in self.device_api_keys.split(",") if k.strip()}

    @property
    def database_name(self) -> str:
        if self.db_name:
            return self.db_name
        path = urlsplit(self.mongo_uri).path.lstrip("/")
        # strip any query string already removed by urlsplit; path is the db
        return path or "finalyearDB"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
