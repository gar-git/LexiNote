# LexiNote Backend (FastAPI + RQ)

## Requirements
- Python 3.14+
- Redis running (local dev)

## Setup
1. Create the environment (already scaffolded in `backend/.venv`)
2. Set `GEMINI_API_KEY` in `backend/.env` (copy from `.env.example`)

## Run (dev)
1. Start Redis:
   - `docker compose up -d redis`

2. Start the API:
   - `backend/.venv/Scripts/uvicorn app.main:app --reload --port 8000`

3. Start the worker:
   - `backend/.venv/Scripts/rq worker lexinote --url redis://localhost:6379/0`

## Endpoints
- `POST /derive` -> `{ job_id }`
- `GET /jobs/{job_id}` -> job status + topics
- `POST /jobs/{job_id}/notes` -> save edited topics
- `GET /jobs/{job_id}/download` -> DOCX

