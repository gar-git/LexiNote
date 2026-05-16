from __future__ import annotations

import json
from typing import Any

import redis


def make_job_key(job_id: str) -> str:
    return f"lexinote:job:{job_id}"


def load_job(r: redis.Redis, job_id: str) -> dict[str, Any] | None:
    raw = r.get(make_job_key(job_id))
    if not raw:
        return None
    return json.loads(raw)


def save_job(r: redis.Redis, job_id: str, data: dict[str, Any], ttl_seconds: int) -> None:
    r.set(make_job_key(job_id), json.dumps(data), ex=ttl_seconds)

