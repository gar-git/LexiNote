from __future__ import annotations

import uuid
from typing import Any

import redis
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.queue import get_queue
from app.schemas import DeriveRequest, JobData, SaveNotesRequest, JobStatus, Topic
from app.utils.redis_store import load_job as load_redis_job
from app.services.docx import topics_to_docx_bytes
from app.worker import derive_job
from app.derive_in_memory import derive_job_in_memory
from app.utils.job_memory_store import load_job as load_memory_job
from app.utils.job_memory_store import update_job as update_memory_job
from app.utils.redis_store import save_job as save_redis_job


router = APIRouter()


@router.post("/derive", response_model=dict[str, str])
def derive(req: DeriveRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    settings = get_settings()
    req.validate_input()

    job_id = uuid.uuid4().hex

    payload = req.model_dump(mode="json")

    if settings.JOB_BACKEND == "redis":
        queue = get_queue()
        # Enqueue a job that will update Redis under our own job_id key.
        queue.enqueue(
            derive_job,
            job_id,
            payload,
            job_id=job_id,
            result_ttl=settings.JOB_TTL_SECONDS,
        )
    else:
        background_tasks.add_task(derive_job_in_memory, job_id, payload)

    return {"job_id": job_id}


@router.get("/jobs/{job_id}", response_model=JobData)
def job_status(job_id: str) -> JobData:
    settings = get_settings()
    if settings.JOB_BACKEND == "redis":
        r = redis.Redis.from_url(settings.REDIS_URL)
        data = load_redis_job(r, job_id)
    else:
        data = load_memory_job(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="Job not found or expired.")

    return JobData.model_validate(data)


@router.post("/jobs/{job_id}/notes")
def save_notes(job_id: str, body: SaveNotesRequest) -> dict[str, str]:
    settings = get_settings()
    if settings.JOB_BACKEND == "redis":
        r = redis.Redis.from_url(settings.REDIS_URL)
        data = load_redis_job(r, job_id)
    else:
        data = load_memory_job(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="Job not found or expired.")

    data["notes"] = [t.model_dump() for t in body.topics]
    data["status"] = JobStatus.notes_saved.value

    # Persist notes back.
    if settings.JOB_BACKEND == "redis":
        assert r is not None
        save_redis_job(r, job_id, data, ttl_seconds=settings.JOB_TTL_SECONDS)
    else:
        # In-memory job already has TTL; we only patch the record.
        update_memory_job(job_id, data)

    return {"status": "saved"}


@router.get("/jobs/{job_id}/download")
def download_docx(job_id: str) -> StreamingResponse:
    settings = get_settings()
    if settings.JOB_BACKEND == "redis":
        r = redis.Redis.from_url(settings.REDIS_URL)
        data = load_redis_job(r, job_id)
    else:
        data = load_memory_job(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="Job not found or expired.")

    topics_raw = data.get("notes") or data.get("topics") or []
    topics = [Topic.model_validate(t) for t in topics_raw]

    # Derive docx label.
    source_label = data.get("sourceLabel") or data.get("source") or "LexiNote"

    doc_bytes = topics_to_docx_bytes(topics=topics, source_label=str(source_label))

    filename = f"LexiNote-{job_id}.docx"
    return StreamingResponse(
        iter([doc_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

