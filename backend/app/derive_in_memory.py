from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.schemas import DeriveRequest, InputType, JobStatus
from app.services.fetch_extract import fetch_url_text, normalize_text
from app.services.generate_notes import generate_topics_with_gemini
from app.utils.job_memory_store import create_or_reset_job, update_job
from app.utils.validator import filter_invalid_topics


def derive_job_in_memory(job_id: str, request_dict: dict[str, Any]) -> None:
    settings = get_settings()
    request = DeriveRequest.model_validate(request_dict)
    request.validate_input()

    source_label = request.sourceLabel or (
        request.url if request.inputType == InputType.url else "User pasted text"
    )

    create_or_reset_job(
        job_id,
        {
            "job_id": job_id,
            "inputType": request.inputType.value,
            "sourceLabel": source_label,
            "status": JobStatus.queued.value,
            "progress": 0,
            "topics": [],
            "notes": None,
            "error": None,
        },
    )

    try:
        update_job(job_id, {"status": JobStatus.running.value, "progress": 5})

        if request.inputType == InputType.url:
            update_job(job_id, {"progress": 15})
            extracted = fetch_url_text(request.url)
        else:
            update_job(job_id, {"progress": 15})
            extracted = normalize_text(request.text or "")

        extracted = extracted[: settings.MAX_INPUT_CHARS]
        if not extracted.strip():
            raise ValueError("No content extracted.")

        update_job(job_id, {"progress": 45})
        draft = generate_topics_with_gemini(source_text=extracted, mode=request.mode)
        validated = filter_invalid_topics(topics=draft, source_text=extracted, mode=request.mode)

        if not validated.topics:
            raise ValueError("Could not generate grounded topic notes from the provided text.")

        update_job(
            job_id,
            {
                "progress": 95,
                "status": JobStatus.done.value,
                "topics": [t.model_dump() for t in validated.topics],
                "coverageNote": validated.coverageNote,
                "coverageScore": validated.coverageScore,
                "error": None,
            },
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
        update_job(job_id, {"status": JobStatus.failed.value, "progress": 100, "error": err_msg})

