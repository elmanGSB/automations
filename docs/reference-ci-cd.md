# CI/CD Reference

The automations repo deploys via GitHub Actions on every push to `main`. Three workflows run:

| Workflow | File | Trigger | What it does |
|----------|------|---------|-------------|
| Deploy Automations | `.github/workflows/deploy.yml` | Push to `main` | Tests → rsync → env setup → migrations → systemd restart → health checks |
| Sync to Windmill | `.github/workflows/wmill-sync.yml` | Push to `main` | Pushes flow definitions to Windmill via `wmill sync push` |
| CI | `.github/workflows/ci.yml` | PRs + pushes | Runs `vm-api` test suite |

Commits prefixed with `[WM]` skip the Windmill sync to prevent Windmill → GitHub → Windmill loops.

---

## Deploy Automations (`deploy.yml`)

Runs on push to `main` only (not PRs). Two jobs: `test` (runs first) and `deploy` (gated on test passing).

### `test` job

Runs `pytest tests/` on `vm-api/` using Python 3.11 with CI dummy env vars. Two classifier tests are deselected — they need a live BAML proxy not available in CI.

### `deploy` job — step by step

**1. SSH setup**  
Writes `DEPLOY_SSH_KEY` secret to `~/.ssh/deploy_key`. Runs `ssh-keyscan` on `DEPLOY_HOST` to populate `known_hosts`.

**2. Rsync code to VM**  
```bash
rsync -az --delete ./ $DEPLOY_USER@$DEPLOY_HOST:/home/elmanamador/automations/
```
Excludes: `.env`, `.venv/`, `.git/`, `__pycache__/`, cache dirs, `vm-api/state.json*`. The `--delete` flag removes files on the VM that were deleted in the repo.

**3. One-time .env migration**  
If `vm-api/.env` doesn't exist at the canonical path (`/home/elmanamador/automations/vm-api/.env`), copies it from the legacy path (`/home/elmanamador/vm-api/.env`). Fails hard if neither exists — vm-api would start without secrets.

**4. Assert FIREFLIES_API_KEY present**  
Greps `vm-api/.env` for `FIREFLIES_API_KEY`, strips dotenv quoting, and fails the deploy if it's empty. Prevents silent 503s on every Fireflies webhook.

**5. Upsert TELEGRAM_* credentials**  
Writes `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from GitHub Secrets into `vm-api/.env` using an `upsert()` shell function (updates existing keys, appends missing ones). Fails if either secret is unset.

**6. Upsert TEABLE_TOKEN**  
Same pattern for `TEABLE_TOKEN`. Missing token would silently drop Teable dual-writes in the discovery pipeline.

**7. Run database migrations**  
SSHes into the VM and runs all `.sql` files in `discovery/` and `vm-api/migrations/` via `docker exec` into the `paperclip-db-1` container. Numbered migrations in `vm-api/migrations/` are idempotent — safe to re-run. `discovery/schema.sql` is a bootstrap script (run once on DB initialization) and is **not** idempotent; re-running it against a live database will error on existing tables.

**8. Install systemd unit**  
Copies `infra/systemd/vm-api.service` from the rsync'd repo into `/etc/systemd/system/` and reloads systemd. Ensures the unit file in `/etc/` always reflects what's in git.

**9. Assert systemd unit points at canonical runtime**  
Verifies `WorkingDirectory`, `ExecStart`, and `EnvironmentFiles` in the installed unit all point at the canonical paths under `/home/elmanamador/automations/vm-api/`. Hard-fails if any path is wrong.

**10. Build venv + install dependencies**  
Creates `.venv` under `vm-api/` if absent, upgrades pip, installs from `requirements.txt`.

**11. Cutover — stop, migrate state.json, start**  
The most complex step. While the service is stopped (no writers can race):
- Migrates `state.json` from legacy path to canonical path if needed
- Runs a divergence guard: if trusting an existing canonical `state.json`, verifies it matches the legacy file byte-for-byte
- Retires the legacy file to `state.json.retired.<ts>` so future deploys don't see it
- A `trap EXIT` restarts vm-api if anything fails after the stop, so production is never left down

**12. Health check vm-api**  
Polls `https://leads.jumpersapp.com/health` with CF Access credentials up to 10 times (3s apart). Fails the deploy if unreachable.

**13. Install claude-proxy systemd unit**  
Copies `infra/systemd/claude-proxy.service` into `/etc/systemd/system/`, enables it, and restarts it. Claude proxy bridges the Max subscription to an HTTP API at `127.0.0.1:8199`.

**14. Health check claude-proxy**  
Polls `http://127.0.0.1:8199/health` on the VM (10 attempts, 2s apart). Claude proxy must be up before LiteLLM config is pushed.

**15. Sync LiteLLM config**  
Copies `infra/litellm/config.yaml` to `/home/elmanamador/litellm/config.yaml` and patches the `api_base` URL with the live `paperclip_default` Docker network gateway IP. The committed config has a default IP (`172.18.0.1`) that may differ after Docker network teardowns.

**16. Restart LiteLLM container**  
Runs `docker restart litellm`. LiteLLM reads config at startup; it does not hot-reload.

**17. Health check LiteLLM**  
Polls `https://llm.jumpersapp.com/health/liveliness` up to 40 times (3s apart, ~2 min total). LiteLLM runs Prisma migrations on every startup — this window is intentionally long.

**18. Prune dangling Docker images**  
Runs `docker image prune -f` to clean up build artifacts.

---

## Required GitHub Secrets

| Secret | Used by | If missing |
|--------|---------|-----------|
| `DEPLOY_SSH_KEY` | All SSH steps | Deploy fails at step 1 |
| `DEPLOY_HOST` | All SSH steps | Deploy fails at step 1 |
| `DEPLOY_USER` | All SSH steps | Deploy fails at step 1 |
| `TELEGRAM_BOT_TOKEN` | Upsert + vm-api alerts | Deploy hard-fails at step 5 |
| `TELEGRAM_CHAT_ID` | Upsert + vm-api alerts | Deploy hard-fails at step 5 |
| `TEABLE_TOKEN` | Upsert + discovery pipeline | Deploy hard-fails at step 6 |
| `CF_ACCESS_CLIENT_ID` | Health checks | Health checks 401 |
| `CF_ACCESS_CLIENT_SECRET` | Health checks | Health checks 401 |

---

## Related

- How-to: [Add a new meeting category](how-to-add-meeting-category.md)
- How-to: [Trigger a pipeline run or backfill](how-to-run-pipeline.md)
- How-to: [Update the jumpersapp.com portal](how-to-portal.md)
- VM API: `vm-api/README.md`
