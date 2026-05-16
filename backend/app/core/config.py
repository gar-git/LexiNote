from __future__ import annotations

from functools import lru_cache
from typing import List, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-2.0-flash"
    # If the configured model isn't available for your API key/account,
    # try these alternatives in order.
    GEMINI_MODEL_FALLBACKS: List[str] = [
        "gemini-2.5-flash",
        "gemini-2.0-flash-lite",
        "gemini-flash-latest",
        "gemini-pro-latest",
    ]

    # Redis connection for RQ + job state.
    REDIS_URL: str = "redis://localhost:6379/0"

    # Dev-friendly default: run background derivations in-process (no Redis).
    # Set to "redis" when you deploy with Redis + RQ worker.
    JOB_BACKEND: Literal["memory", "redis"] = "memory"

    # Ephemeral job lifetime (seconds). After this, /jobs/{job_id} disappears.
    JOB_TTL_SECONDS: int = 2 * 60 * 60

    # Hard safety caps.
    MAX_INPUT_CHARS: int = 150_000
    MAX_URL_DOWNLOAD_BYTES: int = 8 * 1024 * 1024  # 8MB

    # CORS for your frontend dev server.
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # Gemini generation caps (keeps output short/reliable).
    TOPICS_SHORT: int = 5
    TOPICS_BALANCED: int = 7
    TOPICS_DETAILED: int = 10

    BULLETS_PER_TOPIC_SHORT: int = 6
    BULLETS_PER_TOPIC_BALANCED: int = 8
    BULLETS_PER_TOPIC_DETAILED: int = 12

    # Citations/snippets are on by default for “trust”.
    CITATIONS_ENABLED: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

