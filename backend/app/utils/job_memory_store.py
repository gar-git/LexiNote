from __future__ import annotations

import json
import threading
import time
from typing import Any

from app.core.config import get_settings


_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_expires_at: dict[str, float] = {}


def _cleanup_expired() -> None:
    now = time.time()
    expired = [job_id for job_id, exp in _expires_at.items() if exp <= now]
    if not expired:
        return
    with _lock:
        for job_id in expired:
            _jobs.pop(job_id, None)
            _expires_at.pop(job_id, None)


def create_or_reset_job(job_id: str, data: dict[str, Any], ttl_seconds: int | None = None) -> None:
    settings = get_settings()
    ttl = ttl_seconds if ttl_seconds is not None else settings.JOB_TTL_SECONDS
    _cleanup_expired()
    with _lock:
        _jobs[job_id] = json.loads(json.dumps(data))  # deep copy
        _expires_at[job_id] = time.time() + ttl


def update_job(job_id: str, patch: dict[str, Any]) -> None:
    _cleanup_expired()
    with _lock:
        if job_id not in _jobs:
            return
        _jobs[job_id].update(patch)


def load_job(job_id: str) -> dict[str, Any] | None:
    _cleanup_expired()
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        return json.loads(json.dumps(job))


def job_exists(job_id: str) -> bool:
    return load_job(job_id) is not None

