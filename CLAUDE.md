# CLAUDE.md — Automations

Meeting intelligence pipeline and discovery interview pipeline, hosted on the Paperclip VM. Orchestrated via Windmill.

**VM access**: see `tooling/infra/CLAUDE.md`
**Service docs**: `docs/services/automations.md`, `docs/services/discovery.md`

## Modules

| Path | Purpose | CLAUDE.md |
|---|---|---|
| `discovery/` | Customer interview pipeline (BAML extraction → Postgres + Teable) | `discovery/CLAUDE.md` |
| `vm-api/` | FastAPI service on VM :3101 — central pipeline interface | `vm-api/CLAUDE.md` |
| `f/` | Windmill flow definitions | — |
| `infra/` | Deploy scripts, systemd configs | — |

## Stack

Python, BAML, uv, FastAPI, PostgreSQL, Windmill, Telegram alerts, AgentMail

## Deploy Flow

```
git push origin main
  → GitHub Actions (deploy.yml)
  → rsync to /home/elmanamador/automations on VM
  → systemctl restart vm-api
```

Never SCP or edit code on the VM directly. CI/CD handles all deploys.

## Run / Test

See individual module CLAUDE.md files for per-module commands. Top-level:

```bash
cd repos/automations
uv run pytest          # full suite (DB tests need SSH tunnel on port 5433)
```

## Key Constraints

- **DB access for tests**: requires SSH tunnel (`localhost:5433 → VM:5432`). See `tooling/infra/CLAUDE.md`.
- **Claude proxy auth**: subscription-based OAuth (not API key). See `docs/solutions/deployment-issues/` for the known Docker auth issue.
- **Windmill sync**: `wmill sync push` deploys flow definitions. Config in `wmill.yaml`.
- **Dual-write**: discovery writes to Postgres (source of truth) and Teable (best-effort, non-fatal).

## Deploy Configuration (configured by /setup-deploy)
- Platform: Custom GitHub Actions → rsync to Paperclip VM (GCP us-central1-f)
- Production URL: https://leads.jumpersapp.com
- Deploy workflow: .github/workflows/deploy.yml (push to main → test → rsync → systemd restart → health checks)
- Deploy status command: gh run view (monitor GH Actions run triggered by merge commit)
- Merge method: squash
- Project type: web API
- Post-deploy health check: https://leads.jumpersapp.com/health (requires CF Access headers — verified by deploy.yml internally; use `gh run view` to confirm deploy success from local machine)

### Custom deploy hooks
- Pre-merge: none
- Deploy trigger: automatic on push to main (GitHub Actions)
- Deploy status: gh run list --branch main --limit 3 --json name,status,conclusion,headSha
- Health check: poll `gh run view <run-id> --json conclusion` until success (CF Access creds not available locally; deploy.yml runs the actual curl health check on the VM)
