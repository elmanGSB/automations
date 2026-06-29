# VM API

Central HTTP interface for Paperclip VM services. Runs on port 3101.

**Stack**: Python, FastAPI, uv, asyncpg
**Full context**: `docs/services/discovery.md`, `docs/services/automations.md`
**Backfill operations**: see `vm-api/docs/backfill-runbook.md`

## Quick Commands

```bash
cd /Users/elmanamador/coding/repos/automations/vm-api
uv run uvicorn main:app --reload --port 3101   # local dev
uv run pytest tests/                            # full test suite
```

## Deploy to VM

Deploys ride GitHub Actions on push to `main` — `deploy.yml` rsyncs and restarts `vm-api` via systemd. Never SCP code directly to the VM; let CI handle it.

```bash
# Manual restart only — to pick up env changes or after a hand-edit:
gcloud compute ssh paperclip-vm --tunnel-through-iap --zone=us-central1-f \
  --project=paperclip-tribuai -- 'sudo systemctl restart vm-api'
```

## Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | none | Liveness check |
| GET | `/health/full` | Bearer | Checks Postgres + Claude proxy |
| POST | `/api/leads` | none | Demo form lead capture (broccolli.ai) |
| PATCH | `/api/leads/{id}` | none | Update lead pillar |
| GET | `/api/interviews` | Bearer | List recent interviews |
| POST | `/api/pipeline/run` | Bearer | Full meeting pipeline (Windmill calls this on Fireflies events) |
| POST | `/api/digest/run` | Bearer | Weekly aggregate patterns analysis |

`/api/pipeline/run` accepts an optional `force: bool = false` field. `force: true` bypasses the `is_meeting_processed` early-return so a meeting that was processed under buggy code (e.g. pre PR #38, when class meetings were marked processed without uploading) can be replayed. Upload-level idempotency (`is_nlm_uploaded`) still applies.

## Key Constraints

- **Auth**: All `/api/*` and `/health/full` endpoints require `Authorization: Bearer <VM_API_SECRET>`
- **Port 3101**: GCP firewall already allows this — public access still goes through Cloudflare Tunnel + Access
- **Pipeline execution**: `run_meeting_pipeline` is a plain `def` that runs in the FastAPI threadpool — blocking NLM subprocess calls are safe there. See [docs/architecture.md](docs/architecture.md) for the two async dispatch patterns.
- **Discovery extractor**: `discovery_extractor.py` and `teable_client.py` are copied here — keep in sync with `discovery/vm_modules/` when that changes
- **Title overrides**: Meetings with titles starting `Internal:` (case-insensitive) skip the `analyze_novel` + `send_novel_report` steps even when the classifier returns `customer-discovery`. Upload still runs so the transcript is archived. See PR #42 for rationale.
- **Claude proxy auth**: OAuth credentials expire ~24h. The pipeline auto-heals via GCP Secret Manager. See [docs/howto-auth-heal.md](docs/howto-auth-heal.md) for manual recovery.

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `FIREFLIES_API_KEY` | yes | — | Fireflies GraphQL API |
| `VM_API_SECRET` | yes | — | Bearer token for all `/api/*` + `/health/full` endpoints |
| `DATABASE_URL` | no | `postgresql://paperclip:paperclip@127.0.0.1:5432/discovery` | asyncpg pool for discovery DB |
| `TELEGRAM_BOT_TOKEN` | no | `""` | Telegram bot for error alerts + new-category notifications |
| `TELEGRAM_CHAT_ID` | no | `""` | Target chat for Telegram messages |
| `TEABLE_TOKEN` | no | `""` | Teable Personal Access Token (needs record:read + record:create on Interviews DB) |
| `TEABLE_BASE_URL` | no | `http://127.0.0.1:3200` | Teable API base URL |
| `HINDSIGHT_URL` | no | `http://127.0.0.1:8888` | Hindsight MCP service URL |
| `HINDSIGHT_API_KEY` | no | `""` | Bearer token for Hindsight retain calls |
| `LITELLM_BASE_URL` | no | `http://127.0.0.1:4000/v1` | LiteLLM gateway URL — `classify_meeting` calls it |
| `LITELLM_API_KEY` | yes (for classify) | `""` | LiteLLM master key. Deploy upserts it from the `LITELLM_MASTER_KEY` CI secret; empty → classify 401s |
| `LITELLM_MODEL` | no | `claude-sonnet` | LiteLLM model name (legacy/tooling) |
| `CLASSIFY_MODEL` | no | `gemini-3-1-pro` | Model `classify_meeting` uses via LiteLLM; must be a `model_name` in `infra/litellm/config.yaml` |

Missing `TELEGRAM_*` vars silence notifications. Missing `TEABLE_TOKEN` raises `TeableAuthError` on first dual-write attempt and sends a Telegram alert.

## Two-Stage NotebookLM Gating (PR #38)

The pipeline gates NotebookLM work in two stages:

1. **`NLM_UPLOAD_CATEGORIES`** (= `set(KNOWN_CATEGORIES.keys())`) — every named category gets its transcript archived as a per-category notebook source. Ad-hoc / classifier-invented slugs skip entirely to avoid orphan notebooks.
2. **`NLM_ANALYSIS_CATEGORIES`** (= `{"customer-discovery"}`) — only customer-discovery meetings run `analyze_novel` + send the novel-insights email. Other categories have no `[INTERVIEWEE]` speaker so the prompt would return noise.

Before PR #38 these were collapsed into a single `NLM_ENABLED_CATEGORIES = {"customer-discovery"}` that silently skipped uploads for everything else. See `docs/solutions/workflow-issues/notebooklm-upload-silently-skipped-20260517.md` (workspace docs) for the post-mortem.

## Adding a new category

1. `vm-api/config.py` — add `"slug": "Notebook Title"` to `KNOWN_CATEGORIES`. The slug auto-joins `NLM_UPLOAD_CATEGORIES` via `set(KNOWN_CATEGORIES.keys())`.
2. `vm-api/classifier.py` — add `- slug: description` under the Stanford GSB classes section (or the "Known categories" section for non-class slugs).
3. PR + merge + deploy. First meeting in the new category triggers `get_or_create_notebook_id` to auto-create the notebook via `nlm notebook create`.

PR examples: #39 (`class-fin-trading`), #40 (`class-conv-mgmt`, `class-policy`, `class-humor`).
