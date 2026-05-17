# Attio Triage v2 — sub-workflow architecture

**Date:** 2026-05-17 (revised after codex + DHH + Kieran + simplicity reviews)
**Status:** Design — pending review
**Goal:** Handle CSVs of any size reliably through the existing Attio Triage v2 pipeline, without OOM crashes, without 1-hour timeout failures, without operator babysitting.

## Problem statement

The current Attio Triage v2 workflow (`HrQEwEig7NgpcFvi`) processes CSVs of food distributors through domain resolution + Attio CRM enrichment + Hunter/Apollo contact enrichment + XLSX output. It works for files up to ~200-400 rows. Above that:

- **OOM crashes** — verified at 612 rows in exec 463 (`WorkflowCrashedError: Workflow did not finish, possible out-of-memory issue`). All intermediate Attio/Hunter/Apollo payloads + AI responses + accumulated row state pile up in one n8n worker process.
- **1-hour execution cap** — verified at exec 448 (serial 48 AI calls × 50s = 40 min just for resolver).
- **Concurrency thundering herd** — 5 parallel webhook-fanout chunks crashed all 5 due to shared worker memory pressure.

The 612-row run was salvaged by manually chunking into 6 sequential webhook invocations and merging XLSX outputs in Python. Works once, not durable.

## Design history

This is the second revision. The first revision proposed Dispatcher/Worker mode bifurcation inside one workflow, plus a new Consolidator workflow + new Data Tables. Three reviewers (codex, DHH, Kieran, code-simplicity) converged on the same critique: **we were reinventing n8n's built-in primitives** (Execute Workflow, SplitInBatches) and adding state-management debt (new Data Tables) to work around them.

This revision adopts DHH's recommendation: two workflows connected by Execute Workflow, hardened with Kieran's idempotency note.

## Constraints we keep

- n8n Cloud orchestrates everything (operator preference: low maintenance, visual workflow).
- claude-proxy on the VM (subscription Claude, $0 cost) is the resolver engine.
- Existing Attio + Hunter + Apollo + GDrive nodes stay.
- Plan ceiling: 5 concurrent executions per n8n account.
- Single XLSX output per input file (operator preference; chosen in brainstorming Q3).

## Architecture

### Two workflows connected by Execute Workflow

```
┌──────────────────────────────────────────────────────────────────────┐
│  Triage-Main (existing workflow, refactored)                         │
│                                                                      │
│  GDrive Trigger → Download → SHA256 → Manifest claim                 │
│    → Detect File Format → Extract Companies → Dedup                  │
│    → SplitInBatches (size = 100)                                     │
│    ┌─ onEachBatch ──→ Execute Workflow ──→ (wait for return)         │
│    │                  [Triage-Worker]      enriched items            │
│    │                                       ↓                         │
│    │                                       collect in main           │
│    └──── nextBatch ────────────────────────┘                         │
│    → Build single XLSX → Upload to Triage Outbox                     │
│    → Manifest mark success → Move Input to Processed                 │
└──────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ Execute Workflow (sub-workflow call)
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Triage-Worker (new workflow)                                        │
│  workflow concurrency = 3 (n8n setting)                              │
│                                                                      │
│  Execute Workflow Trigger ──→ Has Domain? IF                         │
│  (input: array of                ├─ TRUE  → straight to Attio        │
│   row items)                     └─ FALSE → AI Resolver (claude -p)  │
│                              → Attio Find Company by Domain          │
│                              → Branch Classifier (A/B/C/D)           │
│                              → For Branch D: Hunter → Apollo         │
│                              → return enriched items                 │
└──────────────────────────────────────────────────────────────────────┘
```

The single existing `Pipeline Inbox` folder stays. Operator's mental model unchanged: "drop any CSV in the inbox, get a single XLSX in the outbox."

### Why this solves the structural problems

| Problem | How this design fixes it |
|---|---|
| OOM at 612 rows | Each Triage-Worker invocation processes only 100 rows. Intermediate Attio/Hunter/Apollo payloads are scoped to that sub-execution and garbage-collected on return. Parent only holds the small enriched return values (domain + branch + recommended_action + contact list) — not the bloated raw API responses. |
| 1-hour parent execution cap | Time bound is N_chunks × avg_chunk_time. For 612 rows with chunk=100 and per-chunk ~7 min: 7 × 7 = 49 min sequential — fits under the cap. Sub-workflow parallelism (if n8n's Execute Workflow supports it on the operator's plan) drops this further. See "Open question on parallelism" below. |
| Webhook fanout thundering herd | No webhooks. Execute Workflow is synchronous-from-the-parent's-perspective; n8n's own concurrency setting on Triage-Worker (max 3) caps parallelism naturally. |
| Filename-as-state | Doesn't exist. Sub-workflow input/output is in-memory data, not files. |
| New Data Tables to maintain | Doesn't exist. Existing `triage_runs` manifest is the only state store. |
| "Operator notices missing output" recovery | Sub-workflow errors propagate to the parent as item errors. Parent handles them in one place (failed chunks visible in execution UI, retryable via re-run). |

## Workflow A: Triage-Main (refactored)

### Node changes

**Removed nodes:**
- All current resolver-branch nodes (Build Resolver Batches, AI: Resolve Domains via Web Search, Apply Resolutions) — MOVED to Triage-Worker.
- The Webhook trigger from the previous spec — not needed.
- The "Webhook to File Ref" adapter — not needed.
- Apollo + Hunter nodes in this workflow's body — MOVED to Triage-Worker.

**Kept nodes (no changes):**
- GDrive Trigger
- GDrive: Download File
- Compute SHA256
- Manifest: Lookup, Decide Claim, Should Process?, Manifest: Claim, Log Skip
- Restore Binary
- Detect File Format
- Extract: CSV Companies, Extract: People sheet
- Merge Input Rows
- Dedup Companies, Dedup People
- Build Companies Output (the final XLSX builder)
- Upload Output
- Manifest: Mark Success, Move Input to Processed

**New nodes:**
- `Loop Chunks` (n8n `splitInBatches`, version 3, batch size 100, reset off): splits the deduped 612-row array into batches.
- `Execute Workflow: Triage-Worker` (n8n `executeWorkflow`): inside the SplitInBatches loop's onEachBatch path. Passes the batch's items as input; receives enriched items as output.
- The `Build Companies Output` node moves to AFTER the SplitInBatches loop completes.

### Decide Claim simplification

Removes the `force: true` bypass and the `split_dispatched` status from the previous spec. Only relevant statuses are now `processing` (active run) and `success`. Stale-processing reclaim window stays at 10 minutes (already deployed).

### Concurrency

`Triage-Main` keeps the n8n Cloud default (1). One execution per file drop. Multiple file drops queue naturally.

## Workflow B: Triage-Worker (new)

### Trigger
- `Execute Workflow Trigger` (n8n's native sub-workflow entry point). Input: array of row items, each containing at minimum `name`, `city`, `domain` (may be empty), `linkedin_url`.

### Pipeline
The Worker's pipeline is the existing Triage-Main's resolver + enrichment chain, lifted whole:

```
Execute Workflow Trigger
  → Has Domain? IF
       FALSE branch → AI Resolver (single batch of up to 100 rows; internally
                     dispatched to claude-proxy via the Anthropic node with
                     "search the web" prompt — same as today)
                   → Apply Resolutions
                   → Merge into rows
       TRUE branch  → straight to Attio
  → Loop Companies (item iteration over the batch)
       → Attio: Find Company by Domain
       → Classify Match Count → Branch A/B/C/D
       → If in CRM: Attio Read Company, Attio Query People, Classify Engagement
       → If Branch D: Hunter Domain Search → IF Empty → Apollo Search
       → Per-row enrichment output
  → Return enriched array (last node's output IS the worker's return value)
```

### Internal resolver batching

The worker processes up to 100 rows per invocation. Inside the worker, the AI resolver uses BATCH_SIZE = 15 subagent fan-out (already deployed, tested at 49s per batch). For a 100-row worker invocation: 7 internal AI batches × 49s = ~6 min just for the resolver, plus Attio/Hunter/Apollo per-row (~3 min for 100 rows). Total ~10 min per worker.

### Concurrency

Set Triage-Worker's `Workflow Settings → Concurrency` to **3**. This means up to 3 worker sub-executions run in parallel. (The n8n Cloud account-wide cap is 5; leaving 2 slots free for other workflows.)

### Error handling

The Worker workflow's `Workflow Settings → Error workflow` is set to a global error-notification workflow (separate small workflow, sends Slack alert — out of scope for this spec but listed as a follow-up). Per-node retries stay at maxTries=3 on the Anthropic and HTTP nodes.

## Data contract: Triage-Main → Triage-Worker

### Input to Triage-Worker (one n8n item per row)
```json
{
  "name": "Costco Depot #961",
  "city": "Mira Loma",
  "domain": "",                  // empty triggers resolver path
  "linkedin_url": "",
  "input_row_ids": [22],
  "notes": []
}
```

### Output from Triage-Worker (one n8n item per row, in input order)
```json
{
  "name": "Costco Depot #961",
  "city": "Mira Loma",
  "domain": "costco.com",
  "domain_resolved_from_name": true,
  "branch": "D",
  "in_crm": false,
  "attio_company_id": null,
  "attio_company_domains": [],
  "engagement_status": "no_engagement",
  "contacts_in_crm_count": 0,
  "contacts_found_via_enrichment": 10,
  "enriched_contacts": [ /* Hunter / Apollo enriched contact objects */ ],
  "recommended_action": "new_company_with_contacts",
  "needs_review": false,
  "review_reason": "",
  "notes": ["domain_resolved_from_websearch"],
  "websearch_confidence": "high",
  "websearch_reasoning": "..."
}
```

Parent collects these arrays from each chunk and concatenates them in order. After SplitInBatches completes, parent has the full enriched dataset and builds the single XLSX.

## Idempotency

Single layer: `triage_runs` manifest, keyed by SHA256 of input file.

| Scenario | Behavior |
|---|---|
| Same file SHA dropped twice within 10 min while first run is in flight | Second run sees `processing` status with fresh timestamp → `in_progress_recent` → skips |
| Same file SHA dropped after first run completed successfully | Second run sees `success` status → skips |
| First run crashed; same file dropped >10 min later | Stale `processing` row → `stale_processing_takeover` → claim and re-run |
| Worker chunk fails mid-parent-run | Parent execution shows the failure; manifest stays `processing`; operator inspects, re-runs by re-dropping the file |

No new state stores. No `force` flag. No `triage_batches` table. No `consolidator_locks`.

## Failure modes

| Failure | Effect | Recovery |
|---|---|---|
| Worker invocation OOMs (one chunk's intermediate state too big) | Parent's SplitInBatches loop sees that batch's error; can configure node-level retry. If retries exhausted, parent execution fails. | Reduce internal AI BATCH_SIZE in Triage-Worker; redrop file. |
| Worker exceeds the proxy's 180s subprocess timeout on a Claude call | Anthropic node returns error envelope; node-level retry (maxTries=3) handles transient issues. Persistent failure: that chunk's resolver leaves some domains empty (graceful degradation). | Output XLSX flags `domain_resolution_failed` in notes. |
| Parent execution hits 1h cap | Parent crashes. Manifest stays `processing`. | Stale-takeover catches it on re-drop. Lower per-chunk row count to fit time budget. |
| GDrive trigger doesn't fire (n8n cloud polling lag) | No execution starts. | Operator notices missing output; re-drop or toggle workflow. (Out of scope for this spec — separate known issue with n8n cloud GDrive triggers.) |
| Sub-workflow not found at runtime | Parent's Execute Workflow node errors. | Operator checks workflow IDs; redrop. |

## Performance projection

| File size (deduped rows) | n_chunks @ 100/chunk | Sequential wall time (~10 min/chunk) | Parallel-3 wall time |
|---|---|---|---|
| 100 | 1 | ~10 min | ~10 min |
| 400 | 4 | ~40 min | ~14 min |
| 612 (today's CDFA list) | 7 | ~70 min ⚠️ (exceeds 1h cap) | ~25 min |
| 1000 | 10 | ~100 min ⚠️ | ~35 min |
| 2000 | 20 | ~200 min ⚠️ | ~70 min ⚠️ |

⚠️ Cells exceed n8n's 1h execution cap. Parallel-3 column assumes Execute Workflow with parallel sub-execution is available. This is the open question below.

## Open question on parallelism

**Does n8n's Execute Workflow node run sub-workflows in parallel when called inside a SplitInBatches loop?**

If YES (or if we can pass all batch items at once to Execute Workflow with `runOnceForEachItem` and n8n parallelizes): the design fits 612 rows in ~25 min, well under the cap, and scales to ~1500 rows.

If NO (sub-workflows are strictly sequential): the design fits ~500 rows comfortably. Files >500 rows would either hit the 1h cap OR need a workaround (operator splits manually, or we revisit the spec).

**Test plan to resolve this**: implementation Phase 1.5 runs a controlled test with a 200-row file. If wall time is roughly 2 × (one chunk time), it's sequential. If wall time is roughly 1 × (one chunk time), it's parallel. Based on the result we either:
- Ship as-is (if parallel)
- Or set a documented file-size limit (if sequential) and add operator guidance: "files > 500 rows, split before drop"

## Implementation order

Per code-simplicity reviewer: build the smaller, more-testable workflow first.

1. **Phase 1 — Build Triage-Worker in isolation.** Create the new workflow with Execute Workflow Trigger entry. Lift the resolver + Attio + Hunter + Apollo nodes from Triage-Main as-is. Test by manually triggering with a 5-row sample via the n8n UI's "Execute Workflow" run-with-data feature. Verify return shape matches the data contract above.

2. **Phase 2 — Refactor Triage-Main.** Delete the resolver + Attio + Hunter + Apollo nodes from Triage-Main. Insert `SplitInBatches` (size=100) after Dedup. Insert `Execute Workflow` (Triage-Worker) inside the loop. Verify Build Companies Output runs after the loop completes with concatenated results.

3. **Phase 2.5 — Concurrency test.** Drop a 200-row file. Measure wall time. If ~10 min: sub-workflows are parallel. If ~20 min: sequential.

4. **Phase 3 — Production verification on the 612-row CDFA file.** Compare scorecard to today's manual-chunked baseline (87% resolution, 43 in CRM). Discrepancy >2% in any metric → root-cause before declaring done.

5. **Phase 4 — Set Triage-Worker concurrency to 3.** Configure in n8n's Workflow Settings UI.

6. **Phase 5 — (Optional) Set up global Error workflow.** Tiny separate workflow with Error Trigger → Slack notification. Wire as the "Error workflow" in both Triage-Main and Triage-Worker settings.

## Acceptance criteria

1. **Triage-Worker in isolation**: Manually executing Triage-Worker with 5 hand-crafted row items returns 5 enriched items matching the data contract. Per-row fields populated correctly (domain, branch, in_crm, etc.).

2. **100-row file end-to-end**: Drop a 100-row CSV in Pipeline Inbox. Produces one consolidated XLSX in Triage Outbox within 12 min. Scorecard matches today's exec 465 baseline (≥95% domain resolution on this sample).

3. **612-row file end-to-end**: Drop `Registered_Distributors.csv`. Produces one consolidated XLSX in Triage Outbox. Scorecard matches today's manual-chunked baseline: 535 ± 10 domains resolved, 43 ± 2 in CRM, 77 ± 5 unresolvable. Wall time ≤55 min.

4. **Idempotency**: Drop the same 612-row CSV twice in quick succession. Second drop logs `already_succeeded` and skips. No duplicate output XLSX.

5. **Multi-file drop**: Drop 3 medium files (~200 rows each) simultaneously. All three produce consolidated XLSXs without OOM. Wall times stay reasonable given Triage-Worker concurrency=3 (some sub-execution slots may be shared across the three parent runs).

6. **No new Data Tables created.** Only `triage_runs` exists in the project's n8n Data Tables UI.

7. **No chunked XLSX files in Triage Outbox.** Only consolidated outputs.

## Out of scope (explicit)

- Re-architecting the resolver as a Python service on the VM (codex's preference, deferred per operator's "stay in n8n" preference).
- Building a generic queue/worker pattern for other workflows (this spec is for triage only).
- Cleaning up the existing stuck `processing` manifest rows from past failed runs (operator runs a one-off SQL/Data Table cleanup or waits for 10-min staleness).
- A global Error workflow (recommended follow-up; not blocking).

## Files this design touches

- n8n workflow `HrQEwEig7NgpcFvi` (Attio Triage v2 → Triage-Main): substantial refactor.
- A new n8n workflow `Triage-Worker`: created from scratch (mostly lifted nodes).
- No code in any git repo changes. (The proxy + LiteLLM changes from earlier PRs stay.)
