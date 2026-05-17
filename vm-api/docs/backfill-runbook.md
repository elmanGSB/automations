# Backfill Runbook

When meetings exist in Fireflies but are missing from a NotebookLM notebook, use the steps here to replay them through the pipeline. The default flow is forward-only — these are the tools for catch-up after schema changes, bug fixes, or pre-webhook history.

## Quick reference

| Problem | Tool |
|---------|------|
| Meeting marked `_processed` but never uploaded (e.g. after a gate-logic fix) | `POST /api/pipeline/run` with `force: true` |
| Meeting exists in Fireflies but never reached the pipeline (pre-webhook) | `POST /api/pipeline/run` (no force — meeting isn't in `_processed` yet) |
| Meeting classified to the wrong notebook | Rename in Fireflies → clear `_nlm_uploaded` for the ID → re-POST with `force: true` |
| Source ended up in the wrong notebook and needs cleanup | `nlm source delete <source-id> --confirm` |
| Meeting was deleted from a notebook but you want to prevent re-upload from Fireflies retries | Leave the ID in `_processed` and `_nlm_uploaded` — Fireflies retries short-circuit at `is_meeting_processed` |

## Identifying the backfill set

The pipeline tracks two sets in `state.json`:
- `_processed` — every meeting the pipeline has touched
- `_nlm_uploaded` — every meeting whose transcript is a NotebookLM source

`_processed - _nlm_uploaded` is the gap caused by an upload-skipping bug (PR #38 was the inaugural one). All meetings in this difference are safe to force-replay because upload-level idempotency (`is_nlm_uploaded`) still prevents duplicates for any that *were* uploaded after all.

To find the gap:
```bash
gcloud compute scp paperclip-vm:/home/elmanamador/automations/vm-api/state.json /tmp/state.json \
  --tunnel-through-iap --zone=us-central1-f --project=paperclip-tribuai

python3 - <<'PY'
import json
s = json.load(open("/tmp/state.json"))
processed = set(s.get("_processed", []))
uploaded = set(s.get("_nlm_uploaded", []))
diff = sorted(processed - uploaded)
print(f"BACKFILL GAP: {len(diff)} meetings")
for m in diff: print(f"  {m}")
PY
```

For meetings that never reached the pipeline (pre-webhook era), query Fireflies for all transcripts in the relevant date range and subtract `_processed`:
```bash
# See vm-api/fireflies.py for the API client; rename_meetings.py for an example invocation.
# Pseudo-query: every Fireflies transcript Apr 1 - May 18 NOT in state["_processed"]
```

## Running a backfill

On the VM, `vm-api/.env` holds `VM_API_SECRET`. Hit the API on localhost to skip the Cloudflare Access dance:

```bash
gcloud compute ssh paperclip-vm --tunnel-through-iap \
  --zone=us-central1-f --project=paperclip-tribuai

# On the VM:
cd /home/elmanamador/automations/vm-api
SECRET=$(grep '^VM_API_SECRET=' .env | cut -d= -f2- | tr -d '"' | tr -d "'")

# Single meeting:
curl -X POST http://127.0.0.1:3101/api/pipeline/run \
  -H "Authorization: Bearer $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"meeting_id": "01K...", "force": true}' \
  | python3 -m json.tool
```

For batches, loop through a meeting-ID list and capture the per-step JSON to a JSONL file:
```bash
while read MID; do
  curl -sS -X POST http://127.0.0.1:3101/api/pipeline/run \
    -H "Authorization: Bearer $SECRET" \
    -H "Content-Type: application/json" \
    --max-time 900 \
    -d "{\"meeting_id\": \"$MID\", \"force\": true}" \
  >> /tmp/backfill_results.jsonl
  echo >> /tmp/backfill_results.jsonl
done < /tmp/ids.txt
```

Each meeting takes 14–230 seconds depending on category (customer-discovery is slowest because of `analyze_novel` + email). Plan ~30 seconds average for class meetings, ~60–120s for customer-discovery.

## Side effects to be aware of

`force: true` bypasses **only** the `is_meeting_processed` early-return. Every other idempotency check still applies:

| Step | Dedup mechanism | Safe to replay? |
|------|-----------------|-----------------|
| Notebook lookup | `get_or_create_notebook_id` | yes — reuses existing notebook by category |
| Source upload | `is_nlm_uploaded(meeting_id)` | yes — returns `skipped/already_uploaded` |
| Discovery extraction | No idempotency | **no** — re-runs and may duplicate Postgres rows |
| Novel-insights analysis | No idempotency | **no** — re-runs the LLM |
| Email | No idempotency | **no** — re-sends to `elman@stanford.edu` + `kklara@stanford.edu` |
| Hindsight retention | No idempotency | **no** — duplicates memory entries |

In practice: **`force: true` is safe for class / advisor / investor / team-sync / competitor meetings** because analysis+email are gated to `customer-discovery` only. For customer-discovery meetings, weigh the cost of an extra email + LLM call before forcing.

To replay without firing analysis+email (e.g. when only the upload was missing), the `Internal:` title override (added in PR #42) suppresses analysis+email even when the classifier returns customer-discovery. Renaming the meeting in Fireflies to start with `Internal:` is a manual workaround that requires using the `update_meeting_title` mutation in `vm-api/fireflies.py`.

## Correcting a mis-classified meeting

Classifier sometimes mis-buckets based on title heuristics (e.g. "case study" suffix pulling a Retailer call into the MGE class notebook). To correct:

1. **Rename in Fireflies** so the corrected title biases the next classification:
   ```python
   # On the VM, in /home/elmanamador/automations/vm-api/
   from fireflies import FirefliesClient
   client = FirefliesClient(api_key=os.environ["FIREFLIES_API_KEY"])
   await client.update_meeting_title("01K...", "Retailer: X — customer discovery")
   ```
2. **Delete the wrong source** from the wrong notebook:
   ```bash
   sudo -u elmanamador /home/elmanamador/.local/bin/nlm source list <wrong-notebook-id> \
     | python3 -c "import json,sys; print([s['id'] for s in json.load(sys.stdin) if '<title-fragment>' in s['title'].lower()])"
   sudo -u elmanamador /home/elmanamador/.local/bin/nlm source delete <source-id> --confirm
   ```
3. **Clear from `_nlm_uploaded`** so the force-replay can re-upload (otherwise the upload step skips with `already_uploaded`):
   ```bash
   # Use mark_nlm_uploaded's inverse logic — edit state.json directly under the file lock.
   # Simplest: stop vm-api briefly, edit /home/elmanamador/automations/vm-api/state.json
   # to remove the meeting_id from "_nlm_uploaded", restart.
   ```
4. **Re-POST with `force: true`** — the renamed title now drives classification correctly and the source uploads to the right notebook.

## Eliminating an upload that shouldn't be there

`nlm source delete <source-id> --confirm` removes the source from NotebookLM. To prevent Fireflies retries from re-uploading it, **leave the meeting_id in `_processed`** — that short-circuits any future retry at the very first check in `_run_pipeline`. Removing the ID from `_processed` would re-open the meeting to webhook delivery.

If a customer-discovery meeting was the upload to delete: the analysis email **has already been sent** and cannot be unsent. Plan accordingly.

## Notebook IDs (as of 2026-05-17)

Live notebooks are listed in `state.json` keys that don't start with `_`. Auto-create handles new categories on first upload — no manual notebook creation needed when adding a slug to `KNOWN_CATEGORIES`.

| Category | Notebook ID |
|----------|-------------|
| customer-discovery | `eaa1e4e0-6848-4805-9500-691e167a7035` |
| investor-calls | `cdd9bab5-ead9-4e26-90cc-1ad653ead152` |
| advisors | `74875e7f-1ba2-4b03-ae76-b87250e10260` |
| team-syncs | `d98351b2-4243-4587-bf10-e2afb6ad7413` |
| competitors | `aaaa2c7e-8e2e-4928-94d4-2f7a7b305916` |
| class-mge | `3b257b9d-5892-4470-b7ec-733446eb0656` |
| class-sales | `cffbaada-5c4f-41f7-a4eb-82468b1db86e` |
| class-leadership | `08e732d3-7de0-404e-8e07-c82f444224c7` |
| class-taxes | `84e5e5a6-f427-4a71-9da9-7159e30489c8` |
| class-fsa | `28af2aa5-f594-4815-9610-7f7e5bf03eda` |
| class-fin-trading | `5008ed38-5f53-4dbb-bce5-d8325efde6b1` |
| class-conv-mgmt | `6e7677d5-7d34-4dd4-907d-b33fa4b8545f` |
| class-policy | `4827a126-fb05-4eca-b283-5a246ba6d1b7` |
| class-humor | `3f99ae15-ae48-4b74-af9a-8a020ddcf5cd` |
