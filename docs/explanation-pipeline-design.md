# Meeting Pipeline Design

The pipeline processes every Fireflies meeting through 10 steps: fetch → classify speakers → classify meeting → discovery extraction → NotebookLM notebook → DOCX upload → novel insights analysis → email → mark processed → Hindsight retention.

Three design decisions shape how it works. Each is a deliberate tradeoff.

---

## Why `pipeline_runner.py` is a plain `def`, not `async def`

### The problem

The `nlm` CLI calls in steps 5–7 (NotebookLM notebook creation, source upload, novel insights query) block for 30 seconds to 3 minutes each. Running a blocking call inside an `async def` function stalls the entire FastAPI event loop — every other request (health checks, concurrent pipeline runs) hangs until the CLI finishes.

### The approach

`run_meeting_pipeline()` is a plain `def`. FastAPI automatically runs plain `def` handlers in a thread pool via `run_in_threadpool`, so the event loop stays free. When the pipeline needs to call async code (asyncpg queries, sending Telegram alerts), it dispatches via `asyncio.run_coroutine_threadsafe(coro, loop).result()`, where `loop` is the event loop that owns the connection pool.

```
FastAPI event loop (thread A)
  → run_in_threadpool → thread B (pipeline)
       ↓ blocking NLM CLI calls (safe here)
       ↓ asyncio.run_coroutine_threadsafe(coro, loop)  ← dispatches back to thread A
       ↓ .result()  ← waits for the async work to complete
```

### Trade-offs

- Blocking `httpx` calls in thread B are safe, but async `httpx.AsyncClient` is not — it would create a new event loop and conflict with the one in thread A. The pipeline uses the sync `FirefliesClient` for this reason.
- `asyncio.run()` cannot be used for pool-bound queries because asyncpg connections are not thread-safe across loops. Only `run_coroutine_threadsafe` is safe.

---

## Why `POST /api/pipeline/run` returns 202 immediately

### The problem

Cloudflare terminates HTTP connections that hold open for more than 100 seconds. The full pipeline (all 10 steps, NLM CLI) can take 3–5 minutes. If the Windmill webhook call held the connection open, Cloudflare would drop it and Windmill would retry — triggering a duplicate run.

### The approach

The endpoint returns 202 immediately and runs the pipeline as a FastAPI `BackgroundTask`. The connection is closed before any processing starts, so Cloudflare's timeout never fires. Errors are reported to Telegram rather than to the caller.

There is one exception: `force=True` runs synchronously and returns 200 with the full per-step result. This is intentional — backfill scripts need to inspect the result directly and run one meeting at a time. Concurrent Windmill retries don't apply in the backfill context.

### Trade-offs

- Windmill sees a 202 and marks the job as successful before the pipeline actually finishes. Step-level errors only surface in Telegram. If Telegram is down, errors are silently logged.
- The in-flight guard (`_in_flight` set) prevents concurrent webhook retries from starting duplicate background runs. It's in-memory — it does not survive a process restart.

---

## Why NotebookLM gating is split into two tiers

### The problem

Early versions used a single `NLM_ENABLED_CATEGORIES = {"customer-discovery"}` set that controlled both upload and analysis. This silently skipped uploads for investor calls, team syncs, and classes — those transcripts were never archived.

When we added new categories (classes, advisors), we wanted them archived in searchable notebooks, but running the novel-insights analysis prompt on them returned noise: the prompt looks for `[INTERVIEWEE]` speaker lines, and non-discovery meetings often have no external speaker at all.

### The approach

Two separate constants in `config.py`:

```python
NLM_UPLOAD_CATEGORIES = set(KNOWN_CATEGORIES.keys())  # every named category
NLM_ANALYSIS_CATEGORIES = {"customer-discovery"}       # novel insights + email
```

Any meeting with a known category slug gets its transcript archived as a source in a per-category NotebookLM notebook. Only `customer-discovery` meetings run `analyze_novel` and send the insight email.

Ad-hoc/unknown category slugs (invented by the classifier for unrecognized meeting types) skip NLM entirely to avoid creating orphan notebooks.

### Trade-offs

- The two-tier split means non-discovery meetings accumulate in notebooks but never generate emails. This is intentional — the notebooks are searchable archives for when you want to go back and review a class or investor call.
- Adding a new category to `KNOWN_CATEGORIES` automatically opts it into upload. You have to explicitly add it to `NLM_ANALYSIS_CATEGORIES` to get emails, and that should only happen if the meeting type has external speakers the novel-insights prompt can reason about.

---

## Why the `Internal:` title prefix suppresses analysis and email

### The problem

The classifier uses Claude to assign a category based on meeting title, participants, and transcript content. This works well for most cases, but founders sometimes name team-internal recordings after the topic of discussion — e.g. "Customer Segment Analysis" — which leads the classifier to return `customer-discovery`. This fires a novel-insights email for an internal planning session, not a real customer interview.

### The approach

Any meeting whose title starts with `Internal:` (case-insensitive) skips the `analyze_novel` and `send_novel_report` steps, regardless of what the classifier returns. The transcript still uploads to the per-category notebook so it's archived.

```python
internal_title_override = bool(
    transcript.title and transcript.title.strip().lower().startswith("internal:")
)
```

The title is treated as authoritative for the email decision. The classifier is authoritative for the upload/extraction destination. This is a deliberate split: you may want an `Internal:` customer-discovery meeting to write to Postgres and be archived in the notebook, but not generate a novel-insights email.

### Trade-offs

- The `Internal:` prefix is a convention enforced by the founder, not by the classifier. If someone names a meeting `Internal: real customer call`, the email is suppressed even if it would have contained useful insights.
- The prefix is case-insensitive and checks only the start of the title — `"internal: "`, `"Internal:"`, `"INTERNAL:"` all match.

---

## Related

- Pipeline steps detail: `vm-api/README.md`
- How-to: [Trigger a pipeline run or backfill](how-to-run-pipeline.md)
- How-to: [Add a new meeting category](how-to-add-meeting-category.md)
- Config: `vm-api/config.py`
