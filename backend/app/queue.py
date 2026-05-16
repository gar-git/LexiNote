from __future__ import annotations

from redis import Redis
from rq import Queue

from app.core.config import get_settings


def get_redis() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.REDIS_URL)


def get_queue() -> Queue:
    return Queue("lexinote", connection=get_redis(), default_timeout=60 * 10)  # 10 min

