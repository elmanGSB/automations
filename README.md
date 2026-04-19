# Broccoli AI Automations

Meeting intelligence pipeline: Fireflies webhooks → classify → extract → NotebookLM → email insights. Orchestrated by Windmill, executed on the Paperclip VM.

## System Overview

```
GitHub (this repo)
  ↓  push to main
GitHub Actions → wmill sync push → Windmill

Fireflies transcript ready
  ↓
Windmill: fireflies_webhook flow
  ↓ validate event
  ↓ POST /webhook/fireflies → VM API (paperclip-vm :3101)
     ↓ 10-step pipeline (see vm-api/README.md)
     ↓ results per step returned as structured JSON
  ↓ alert on fatal step errors (Telegram)

Monday 9am UTC
  ↓
Windmill: weekly_digest flow
  ↓ POST /api/digest/run → VM API
     ↓ NotebookLM aggregate patterns analysis
     ↓ email report to founders (AgentMail)
  ↓ alert on failure (Telegram)

Every 30 min
  ↓
Windmill: health_check flow
  ↓ GET /health/full → VM API
     ↓ checks: Postgres + Claude proxy
  ↓ alert if degraded (Telegram)
```

## Windmill Flows

| Flow | Path | Trigger | Purpose |
|------|------|---------|---------|
| `fireflies_webhook` | `f/discovery/fireflies_webhook.flow` | Fireflies webhook event | Validate → run 10-step meeting pipeline → Telegram on error |
| `weekly_digest` | `f/automations/weekly_digest.flow` | Monday 9am UTC | Aggregate patterns analysis → email report to founders |
| `health_check` | `f/automations/health_check.flow` | Every 30 min | Ping VM health endpoint → Telegram alert if degraded |

## VM API

The pipeline logic runs on the Paperclip VM (`paperclip-vm`, port 3101). See [`vm-api/README.md`](vm-api/README.md) for the full 10-step pipeline, category filters, idempotency design, and deployment instructions.

**Endpoints used by Windmill:**

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/webhook/fireflies` | Bearer token | Run full meeting pipeline |
| `POST` | `/api/digest/run` | Bearer token | Run weekly patterns analysis + email |
| `GET` | `/health/full` | Bearer token | Check Postgres + Claude proxy |
| `GET` | `/health` | None | Liveness check |

## Emails Sent

All emails come from `customer_discovery@agentmail.to` to `elman@stanford.edu` and `kklara@stanford.edu`.

| Email | Trigger | Subject pattern |
|-------|---------|----------------|
| Novel insights | After each new `customer-discovery` meeting | `[Customer Discovery] New Interview: <title>` |
| Weekly patterns | Monday 9am UTC | `[Weekly] Interview Patterns — Customer Discovery` |

Only `customer-discovery` meetings generate emails. All other categories (classes, investor calls, team syncs, advisors, tools-research) are classified and stored but skip NotebookLM and email entirely.

## Meeting Categories

| Slug | Description | Email? |
|------|-------------|--------|
| `customer-discovery` | Customer interviews, sales calls, prospect demos | ✅ |
| `investor-calls` | VCs, angels, fundraising | — |
| `team-syncs` | Internal standups, retrospectives | — |
| `competitors` | Competitive research calls | — |
| `advisors` | Advisor/mentor meetings — business strategy and growth guidance | — |
| `tools-research` | Technical tool evaluation, software product demos | — |
| `class-mge` | Managing Growing Enterprises | — |
| `class-sales` | Building Sales Organizations | — |
| `class-leadership` | The Art of Leading in Challenging Times | — |
| `class-taxes` | Taxes and Business Strategy | — |
| `class-fsa` | Financial Statement Analysis | — |

## CI/CD

Pushing to `main` automatically syncs all Windmill flows, schedules, and variables via GitHub Actions (`.github/workflows/wmill-sync.yml`). Commits prefixed with `[WM]` are skipped to prevent Windmill → GitHub → Windmill loops.

```bash
# Sync manually if needed
wmill sync push --yes --skip-secrets \
  --workspace broccolli-ai-automations \
  --token $WMILL_TOKEN \
  --base-url https://app.windmill.dev/
```

## Workspace

- **Windmill:** `broccolli-ai-automations` at app.windmill.dev
- **VM:** `paperclip-vm` (GCP `us-central1-f`, project `paperclip-tribuai`)
- **VM API port:** 3101

## Repository Structure

```
f/                        Windmill flows (synced on push to main)
  discovery/
    fireflies_webhook.flow/
  automations/
    weekly_digest.flow/
    health_check.flow/
vm-api/                   VM API — FastAPI app with full pipeline logic
  main.py
  pipeline_runner.py
  classifier.py
  emailer.py
  ...
.github/workflows/
  wmill-sync.yml          Auto-sync to Windmill on push to main
wmill.yaml                Windmill sync config
```
