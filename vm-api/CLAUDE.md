# VM API

Central HTTP interface for Paperclip VM services. Runs on port 3101.

**Stack**: Python, FastAPI, uv, asyncpg
**Full context**: `docs/services/discovery.md`, `docs/services/automations.md`

## Quick Commands

```bash
cd /Users/elmanamador/coding/vm-api
uv run uvicorn main:app --reload --port 3101   # local dev
```

## Deploy to VM

```bash
gcloud compute scp -r /Users/elmanamador/coding/vm-api paperclip-vm:~/ --zone=us-central1-f
gcloud compute ssh paperclip-vm --zone=us-central1-f -- 'sudo systemctl restart vm-api'
```

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | /health | Liveness check |
| GET | /health/full | Checks Postgres + Claude proxy |
| POST | /api/leads | Demo form lead capture (broccolli.ai) |
| PATCH | /api/leads/{id} | Update lead pillar |
| GET | /api/interviews | List recent interviews |
| POST | /api/pipeline/run | Full meeting pipeline (Windmill calls this on Fireflies events) |
| POST | /api/digest/run | Weekly aggregate patterns analysis |

## Key Constraints

- **Auth**: All `/api/*` and `/health/full` endpoints require `Authorization: Bearer <VM_API_SECRET>`
- **Env vars**: `DATABASE_URL`, `FIREFLIES_API_KEY`, `VM_API_SECRET`, `TEABLE_EMAIL`, `TEABLE_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- **Port 3101**: GCP firewall already allows this — no changes needed
- **Pipeline execution**: `run_meeting_pipeline` runs synchronously in the FastAPI threadpool; Windmill holds the connection until the structured per-step result is returned
- **Discovery extractor**: `discovery_extractor.py` and `teable_client.py` are copied here — keep in sync with `discovery/vm_modules/` when that changes
