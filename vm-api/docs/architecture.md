# vm-api Architecture

Explanation of the design decisions inside the vm-api service. For the pipeline steps, filters, and operational commands see [README.md](../README.md) and [CLAUDE.md](../CLAUDE.md).

## Module dependency graph

```
main.py
└── pipeline_runner.py
    ├── fireflies.py           → Fireflies GraphQL API
    ├── speaker_roles.py
    ├── transcript_formatter.py
    ├── classifier.py          → claude-proxy :8199
    │   └── ClassifyAuthError  ← raised on HTTP 401
    ├── discovery_extractor.py
    │   ├── claude-proxy :8199
    │   ├── asyncpg pool
    │   └── teable_client.py   → Teable :3200
    ├── docx_generator.py
    ├── notebooklm.py          → nlm CLI subprocess
    ├── analyzer.py            → nlm CLI subprocess
    ├── emailer.py             → AgentMail API
    ├── state.py               → state.json (fcntl flock)
    ├── hindsight.py           → Hindsight MCP :8888
    └── notifier.py            → Telegram API
```

---

## Why `run_meeting_pipeline` is `def`, not `async def`

FastAPI runs plain `def` endpoint handlers in a thread pool via `run_in_threadpool`. The `nlm` CLI subprocess calls in `notebooklm.py` and `analyzer.py` block for 1–3 minutes each. If `run_meeting_pipeline` were `async def`, every `subprocess.run()` call would stall the FastAPI event loop and freeze all other endpoints for the full duration.

Keeping it a plain `def` means FastAPI dispatches it to a worker thread; the event loop stays free for health checks and other requests.

---

## Two async dispatch patterns inside the threadpool

The pipeline thread cannot `await` — but it still needs to drive async I/O. Two patterns are used for different reasons.

### `asyncio.run(coro)` — stateless coroutines

Creates a fresh event loop, runs the coroutine, destroys it:

- `_fetch_with_cleanup()` — httpx client opened and closed in one shot
- `classify_meeting(...)` — stateless httpx call to claude-proxy
- `retain_meeting(...)` / `retain_novel_insights(...)` — stateless Hindsight call
- `send_novel_report(...)` — stateless AgentMail call

### `_run_on_loop(coro, loop)` — pool-bound coroutines

Submits to the FastAPI event loop that owns the asyncpg pool:

- `process_discovery_meeting(...)` — uses the asyncpg connection pool

asyncpg connections are bound to the loop that created them. Running an asyncpg coroutine on a different loop raises `RuntimeError: attached to a different loop`. `_run_on_loop` uses `asyncio.run_coroutine_threadsafe(coro, loop).result()` to execute the coroutine on the correct loop.

---

## Two-stage NotebookLM gating

```
NLM_UPLOAD_CATEGORIES  (= set(KNOWN_CATEGORIES.keys()) — all 14+ named slugs)
  → notebook create + DOCX upload

  └── NLM_ANALYSIS_CATEGORIES  (= {"customer-discovery"})
        → analyze_novel() + send_novel_report()
```

**Why two layers, not one:**

All named categories get transcripts archived so the team can later search any notebook for context — investor calls, class recordings, advisor sessions.

Only `customer-discovery` meetings have an `[INTERVIEWEE]` speaker. The novel-insights prompt explicitly instructs the model to extract insights only from `[INTERVIEWEE]` lines. Other categories produce monologue or internal-only speech; the prompt returns noise on them.

Ad-hoc slugs (invented by the classifier for unknown meeting types) skip upload entirely to prevent orphan notebooks accumulating in NotebookLM.

---

## Auth auto-heal loop

Claude OAuth tokens on the VM expire after ~24 hours. The pipeline heals itself without manual intervention:

1. `classifier.py` checks `response.status_code == 401` before `raise_for_status()` and raises `ClassifyAuthError`.
2. `_run_pipeline()` catches `ClassifyAuthError` around the classify step.
3. `_refresh_claude_credentials()` pulls a fresh token from GCP Secret Manager (`claude-code-credentials`, project `paperclip-tribuai`) and writes it atomically to `~/.claude/.credentials.json`.
4. The classify step retries once. If it still fails, the pipeline returns `auth_refresh_failed` in the step result and exits.
5. A 60-second cooldown (`_CREDS_REFRESH_COOLDOWN`) prevents tight-loop refresh when Secret Manager is slow or returning bad data.

For manual credential recovery see [howto-auth-heal.md](howto-auth-heal.md).

---

## State model

`state.json` is a single JSON file protected by `fcntl.flock` exclusive locks.

| Key pattern | Type | Meaning |
|-------------|------|---------|
| `"customer-discovery"` etc. | string (UUID) | Maps each category slug to its NotebookLM notebook ID |
| `"_processed"` | `[string]` | All meeting IDs the pipeline has completed — never evicted |
| `"_nlm_uploaded"` | `[string]` | Meeting IDs whose DOCX has been uploaded to NLM |

**Two lock files:**

- `state.json.lock` — global write lock used by every read-modify-write operation
- `state.json.create-<category>.lock` — per-category lock for `get_or_create_notebook_id`

The per-category lock means a slow `nlm notebook create` subprocess (up to 120s) does not block unrelated state writes (`mark_processed`, `mark_nlm_uploaded` for other concurrent meetings).

**Why `_processed` is never evicted:**

`is_meeting_processed` is the pipeline's top-level idempotency gate. Evicting old IDs would let delayed Fireflies webhook retries reprocess past meetings — duplicating discovery extraction rows, re-firing emails, and creating duplicate Hindsight entries. The list grows at ~30 bytes per meeting ID; at 10 meetings/day for five years that is ~550 KB — trivial for a JSON load on every webhook.

---

## `Internal:` title override

Meetings titled `Internal:*` (case-insensitive prefix) skip `analyze_novel` and `send_novel_report` even when the classifier returns `customer-discovery`. Upload to the per-category notebook still runs.

This exists because founders use `Internal:` for team recordings that happen to discuss food distribution topics — the classifier classifies on content and sometimes returns `customer-discovery`. The title prefix is the authoritative gate for whether an email fires; the classifier is used only to route the upload to the right notebook.

---

## In-flight guard

`_in_flight: set[str]` in `pipeline_runner.py` prevents two concurrent webhook deliveries for the same meeting ID from both entering the pipeline simultaneously. The set is cleared in a `finally` block.

Unlike `is_meeting_processed` (file I/O, persists across restarts), `_in_flight` is in-memory only. A VM restart clears it. It is intentionally **not** bypassed by `force=True`.

---

## Dual-write to Teable

Postgres is the source of truth. Teable is a best-effort UI layer:

- Writes run in a thread with a 10-second timeout (`asyncio.wait_for(asyncio.to_thread(...), timeout=10.0)`).
- All non-auth errors are logged at WARNING and swallowed.
- `TeableAuthError` (HTTP 401/403) is escalated to a Telegram alert because it is systemic — every future write fails until the PAT is rotated. Regular non-auth failures (network blip, field mismatch) are transient and can be backfilled separately.

---

## Fireflies User-Agent

`FirefliesClient` sends a custom `User-Agent: broccoli-ai-automations/1.0`. Cloudflare in front of `api.fireflies.ai` blocks the default `python-httpx/<version>` user agent with HTTP 403.
