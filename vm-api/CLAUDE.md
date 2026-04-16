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
| POST | /webhook/fireflies | Fireflies extraction trigger (from Windmill) |

## Key Constraints

- **Auth**: `/webhook/fireflies` requires `Authorization: Bearer <VM_API_SECRET>`
- **Env vars**: `DATABASE_URL`, `FIREFLIES_API_KEY`, `VM_API_SECRET`, `TEABLE_EMAIL`, `TEABLE_PASSWORD`
- **Port 3101**: GCP firewall already allows this — no changes needed
- **Background tasks**: Fireflies extraction runs async after 202 response; check VM logs for results
- **Discovery extractor**: `discovery_extractor.py` and `teable_client.py` are copied here — keep in sync with `discovery/vm_modules/` when that changes
