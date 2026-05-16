from __future__ import annotations

import uuid
from typing import Any

from redis import Redis

from app.core.config import get_settings
from app.queue import get_redis
from app.schemas import DeriveRequest, InputType, JobData, JobStatus
from app.services.fetch_extract import fetch_url_text, normalize_text
from app.services.generate_notes import generate_topics_with_gemini
from app.services.docx import topics_to_docx_bytes  # noqa: F401 (imported for future use)
from app.utils.redis_store import save_job
from app.utils.validator import filter_invalid_topics


def _make_initial_job_data(*, job_id: str, request: DeriveRequest, source_label: str) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "inputType": request.inputType.value,
        "sourceLabel": source_label,
        "status": JobStatus.queued.value,
        "progress": 0,
        "topics": [],
        "notes": None,
        "error": None,
    }


def _update_job(r: Redis, *, job_id: str, patch: dict[str, Any], ttl_seconds: int) -> None:
    existing = r.get(f"lexinote:job:{job_id}")
    if existing:
        import json

        data = json.loads(existing)
    else:
        data = {"job_id": job_id}
    data.update(patch)
    save_job(r, job_id, data, ttl_seconds=ttl_seconds)


def derive_job(job_id: str, request_dict: dict[str, Any]) -> None:
    settings = get_settings()
    r = get_redis()
    request = DeriveRequest.model_validate(request_dict)
    request.validate_input()

    source_label = request.sourceLabel or (request.url if request.inputType == InputType.url else "User pasted text")

    # Initialize job data (ephemeral).
    save_job(r, job_id, _make_initial_job_data(job_id=job_id, request=request, source_label=source_label), settings.JOB_TTL_SECONDS)

    try:
        _update_job(r, job_id=job_id, patch={"status": JobStatus.running.value, "progress": 5}, ttl_seconds=settings.JOB_TTL_SECONDS)

        if request.inputType == InputType.url:
            _update_job(r, job_id=job_id, patch={"progress": 15}, ttl_seconds=settings.JOB_TTL_SECONDS)
            extracted = fetch_url_text(request.url)
        else:
            _update_job(r, job_id=job_id, patch={"progress": 15}, ttl_seconds=settings.JOB_TTL_SECONDS)
            extracted = normalize_text(request.text or "")

        extracted = extracted[: settings.MAX_INPUT_CHARS]
        if not extracted.strip():
            raise ValueError("No content extracted.")

        _update_job(r, job_id=job_id, patch={"progress": 45}, ttl_seconds=settings.JOB_TTL_SECONDS)
        draft = generate_topics_with_gemini(source_text=extracted, mode=request.mode)
        validated = filter_invalid_topics(topics=draft, source_text=extracted, mode=request.mode)

        if not validated.topics:
            raise ValueError("Could not generate grounded topic notes from the provided text.")

        _update_job(
            r,
            job_id=job_id,
            patch={
                "progress": 95,
                "status": JobStatus.done.value,
                "topics": [t.model_dump() for t in validated.topics],
                "coverageNote": validated.coverageNote,
                "coverageScore": validated.coverageScore,
                "error": None,
            },
            ttl_seconds=settings.JOB_TTL_SECONDS,
        )
    except Exception as e:
        err_msg = str(e)
        last_attempt = getattr(e, "last_attempt", None)
        if last_attempt is not None:
            try:
                exc = last_attempt.exception()
                if exc:
                    err_msg = str(exc)
            except Exception:
                pass
        _update_job(
            r,
            job_id=job_id,
            patch={"status": JobStatus.failed.value, "progress": 100, "error": err_msg},
            ttl_seconds=settings.JOB_TTL_SECONDS,
        )

