# Attio Triage v2 — split-and-queue architecture

**Date:** 2026-05-17
**Status:** Design — pending review
**Goal:** Handle CSVs of any size reliably through the existing Attio Triage v2 n8n workflow, without OOM crashes, without 1-hour timeout failures, without manual chunking dances.

## Problem statement

The current Attio Triage v2 workflow (`HrQEwEig7NgpcFvi`) processes CSVs of California-registered food distributors through domain resolution + Attio CRM enrichment + Hunter/Apollo contact enrichment + XLSX output. It works for files up to ~200-300 rows. Above that:

- **OOM crashes** (`WorkflowCrashedError: Workflow did not finish, possible out-of-memory issue`) — verified at 612 rows in exec 463. n8n Cloud's worker memory cannot hold all the row state + accumulated AI responses + intermediate Attio/Hunter/Apollo payloads + XLSX assembly state at once.
- **1-hour execution cap** — verified at exec 448 (serial 48 AI calls × 50s = 40 min just for resolver).
- **Concurrency thundering herd** — firing 5 parallel chunks from a webhook crashed all 5 due to combined worker memory pressure (execs 466-470).

The 612-row run was salvaged by manually chunking into 6 sequential webhook invocations and merging XLSX outputs in Python. This works once but is not durable.

## Constraints we keep

- n8n Cloud orchestrates everything (operator preference: low maintenance, visual workflow).
- claude-proxy on the VM (subscription Claude, $0 cost) is the resolver engine.
- Existing Attio + Hunter + Apollo + GDrive nodes stay.
- Plan ceiling: 5 concurrent executions per n8n account.

## Architecture

### Two-folder, three-workflow design

```
                                                ┌──────────────────────────┐
                                                │   Triage Workflow        │
                                                │   (existing, modified)   │
                                                │   concurrency = 3        │
                                                └────────────┬─────────────┘
                                                             │
                ┌──────────────────────────┐                 │
[ Pipeline ───→ │  GDrive Trigger          │ ───→ chunk run? │
   Inbox ]     │  Webhook                  │      yes → fire N webhooks (offset/limit) and exit
                └──────────────────────────┘      no  → process inline → output to Triage Outbox
                                                                                   │
                                                                                   ▼
                                                                          [ Triage Outbox ]
                                                                                   │
                                                                                   ▼
                                                                ┌──────────────────────────┐
                                                                │   Consolidator Workflow  │
                                                                │   (new)                  │
                                                                │   detects chunk pattern, │
                                                                │   merges when batch done │
                                                                └──────────┬───────────────┘
                                                                           │
                                                                           ▼
                                                            [ Triage Outbox ] (final consolidated XLSX)
                                                                           ↑
                                                                           └ chunk XLSXs are deleted
```

The single existing `Pipeline Inbox` folder stays. Operator's mental model: "drop any-size CSV in the inbox, get a final XLSX in the outbox."

### Workflow A: Triage (existing, modified)

Mode is determined by the webhook payload (or absence of one for GDrive-triggered runs):

| Mode | Trigger | Payload shape | Behavior |
|---|---|---|---|
| **Dispatcher** | GDrive trigger OR webhook without `offset`/`limit` | `{file_id, file_name, force?}` | Detects file size, decides whether to split, fires chunk webhooks if needed, exits without producing output. |
| **Worker** | Webhook with `offset` and `limit` set | `{file_id, file_name, force, offset, limit, batch_id, total_rows}` | Processes the specified slice, outputs a chunk XLSX named `<original>__chunk_<offset>_of_<total>_<batch_id>.xlsx`. |
| **Inline** | GDrive trigger OR webhook, file is ≤200 rows | `{file_id, file_name, force?}` | Acts as a single worker over the whole file. Outputs `<original>.xlsx` (no chunk pattern). |

#### Decision logic (one new node after Dedup Companies)

```js
// "Detect Mode" Code node, runs once for all items
const webhookBody = (() => {
  try {
    const wh = $('Webhook: Manual Trigger').first();
    return (wh && wh.json && wh.json.body) || {};
  } catch (e) { return {}; }
})();

const SPLIT_THRESHOLD = 200;
const CHUNK_SIZE = 100;
const rowCount = $input.all().length;
const hasOffsetLimit = (typeof webhookBody.offset === 'number') && (typeof webhookBody.limit === 'number');

let mode;
if (hasOffsetLimit) {
  mode = 'worker';
} else if (rowCount > SPLIT_THRESHOLD) {
  mode = 'dispatcher';
} else {
  mode = 'inline';
}

return [{ json: { mode, rowCount, webhookBody } }];
```

A new IF node `Is Dispatcher?` routes:
- **Dispatcher branch**: Build chunk list → Loop → HTTP Request (fire webhook per chunk) → Exit (no XLSX produced).
- **Worker/Inline branch**: existing flow continues unchanged (Has Domain? → resolver → Attio → ... → Upload Output).

#### Chunk dispatch

```js
// "Build Dispatch Payloads" Code node
const items = $input.all();
const CHUNK_SIZE = 100;
const fileId = $('GDrive: Download File').first().json.id;
const fileName = $('GDrive: Download File').first().json.name;
const batchId = $('Compute SHA256').first().json.file_sha1.slice(0, 8);
const totalRows = items.length;
const payloads = [];
for (let offset = 0; offset < totalRows; offset += CHUNK_SIZE) {
  payloads.push({ json: {
    file_id: fileId,
    file_name: fileName,
    force: true,
    offset,
    limit: Math.min(CHUNK_SIZE, totalRows - offset),
    batch_id: batchId,
    total_rows: totalRows
  }});
}
return payloads;
```

Then an HTTP Request node hits its own webhook URL (`POST https://broccolliai.app.n8n.cloud/webhook/triage-fire`) per item. With workflow concurrency = 3, n8n queues these and runs three at a time.

#### Worker output filename

The existing "Upload Output" node's filename is built from the input file name. Modify the filename builder to append the chunk marker when in worker mode:

```js
const mode = $('Detect Mode').first().json.mode;
const body = $('Detect Mode').first().json.webhookBody;
const sha8 = $('Compute SHA256').first().json.file_sha1.slice(0, 8);
const baseName = (originalName || 'output').replace(/\.csv$/i, '').replace(/\.xlsx$/i, '');
let outName;
if (mode === 'worker') {
  outName = `${baseName}__chunk_${body.offset}_of_${body.total_rows}_${body.batch_id}.xlsx`;
} else {
  outName = `${baseName}.xlsx`;
}
```

This keeps inline runs producing clean output, and worker runs producing identifiable chunks.

#### Concurrency cap

Set the Triage workflow's concurrency setting to **3** in n8n Cloud (`Settings → Workflow concurrency`). Empirically:
- 1 chunk × 100 rows works comfortably.
- 5 concurrent chunks OOMs.
- 3 is untested but a reasonable midpoint; if it fails we drop to 2.

#### Worker mode notes

- Workers bypass the manifest via `force: true` since the dispatcher already claimed the manifest row.
- Workers do not write to the manifest. The dispatcher writes a `split_dispatched` row; the Consolidator writes the final `success` row when merging.

### Workflow B: Consolidator (new)

Watches `Triage Outbox` for chunk-pattern files. When all chunks of a batch arrive, merges into one XLSX.

#### Trigger
- GDrive trigger on `Triage Outbox` (`fileCreated`).
- Skip non-chunk files (filename doesn't match `__chunk_\d+_of_\d+_[a-f0-9]+\.xlsx$`).

#### Logic

```
GDrive Trigger
  → Parse Filename (Code: extract batch_id, total_rows, offset from filename)
  → If pattern doesn't match: exit silently
  → GDrive Search (parent = Triage Outbox, name contains batch_id)
  → Code: Compute expected chunk count = ceil(total_rows / CHUNK_SIZE)
  → If found count < expected: exit silently (other chunks still pending)
  → Loop chunks:
       GDrive: Download File
       Read XLSX rows (n8n's Spreadsheet File node)
  → Merge: concatenate all rows
  → Convert to XLSX (Spreadsheet File node)
  → Upload to Triage Outbox: <original>_consolidated.xlsx
  → Loop chunks: GDrive: Delete File (delete each chunk)
  → Manifest: Mark Success (update triage_runs row with consolidated file id)
```

#### Race conditions
- Two consolidator runs firing for the same batch (last two chunks arrive in quick succession): use a small Data Table `consolidator_locks` keyed by `batch_id` with a 5-min TTL; first run claims, second exits.
- Partial batch (one chunk fails): Consolidator never fires for that batch. Operator notices missing consolidated output → re-fires the failed chunk's webhook manually.

### Workflow A wiring changes summary

New nodes:
- `Detect Mode` (Code) — after Dedup Companies.
- `Is Dispatcher?` (IF) — routes dispatcher vs worker/inline.
- `Build Dispatch Payloads` (Code) — only in dispatcher branch.
- `HTTP Request: Fire Chunk Webhook` (HTTP Request) — only in dispatcher branch.

Modified nodes:
- `Upload Output` filename builder — appends `__chunk_<offset>_of_<total>_<batch_id>` when in worker mode.

No nodes deleted.

### Workflow B sketch (~8 nodes)

- `GDrive Trigger: Triage Outbox` (filtered to fileCreated)
- `Parse Filename` (Code)
- `Match Chunk Pattern?` (IF)
- `Search Outbox by batch_id` (GDrive Search)
- `All Chunks Present?` (Code + IF)
- `Download + Read Chunks` (loop)
- `Merge Rows` (Code or Spreadsheet)
- `Upload Consolidated` (GDrive Upload)
- `Delete Chunks` (loop GDrive Delete)
- `Manifest: Mark Success`

## Data contract

### Webhook payload (worker mode)
```json
{
  "file_id": "1G99RqUZWYLt3gclmN3oNwTWGYJqH_Irp",
  "file_name": "Registered_Distributors.csv",
  "force": true,
  "offset": 100,
  "limit": 100,
  "batch_id": "c25a0402",
  "total_rows": 612
}
```

### Chunk XLSX filename
```
<basename>__chunk_<offset>_of_<total>_<batch_id>.xlsx
e.g. Registered_Distributors__chunk_100_of_612_c25a0402.xlsx
```

### Consolidated XLSX filename
```
<basename>_consolidated.xlsx
e.g. Registered_Distributors_consolidated.xlsx
```

## Idempotency

| Layer | Mechanism |
|---|---|
| Triage Dispatcher | SHA256 of input file → `triage_runs` row, status = `split_dispatched`. Re-trigger on same SHA = skip (existing manifest logic). |
| Triage Worker | `force: true` bypasses manifest. Each worker is the responsibility of its dispatcher. |
| Consolidator | `consolidator_locks` data table prevents double-merge. Filename of consolidated output is deterministic — duplicate uploads overwritten, not duplicated. |

## Failure modes and recovery

| Failure | Detection | Recovery |
|---|---|---|
| Dispatcher crashes mid-fanout | Some chunks fired, some not. | Operator re-fires the original (force=true). Already-completed chunks are no-ops because the original manifest row is `split_dispatched`. Missing chunks rerun. |
| Worker OOMs | Chunk XLSX never lands in Outbox. | Consolidator never fires. Operator notices missing consolidated output. Re-fires that specific chunk webhook manually with same `offset`/`limit`/`batch_id`. |
| Consolidator runs prematurely | Has fewer chunks than expected; exits silently. | Next chunk arrival re-triggers consolidator. Idempotent. |
| Consolidator merges twice | `consolidator_locks` prevents this. | N/A |
| Chunk file deleted between Consolidator's search and download | One chunk download fails. | Consolidator should retry or log + exit (operator re-fires manually). |

## Performance projection

| File size (deduped rows) | Mode | Wall time |
|---|---|---|
| ≤200 | inline | 5-25 min |
| 200-600 | split into 2-6 chunks | ~25 min with concurrency=3 (2 waves of 3) |
| 600-1200 | split into 6-12 chunks | ~50 min with concurrency=3 (4 waves) |
| 2000 | split into 20 chunks | ~83 min |

This puts the 612-row test at ~25 min (vs. 76 min serial chunking we just did manually).

## Out of scope (for this spec)

- Re-architecting the resolver to use a Python worker on the VM (covered in adversarial review; potential future work if this design hits its own limits).
- Cleanup of stuck `processing` manifest rows (the 2-min staleness window we set is sufficient for normal operation).
- Retry strategy for transient claude-proxy errors (n8n node's existing retry config is sufficient).

## Open questions

None.

## Acceptance criteria

1. Dropping a 100-row CSV in Pipeline Inbox produces one consolidated XLSX in Triage Outbox within 15 min. No chunk files remain in Outbox.
2. Dropping the 612-row CDFA Registered_Distributors CSV produces one consolidated XLSX matching the 612-row scorecard we just verified (87% domain resolution, 43 in CRM). No chunk files remain in Outbox. Wall time ≤40 min.
3. Dropping 3 medium files (~300 rows each) simultaneously: all three produce consolidated XLSXs without OOM. Wall time ≤90 min.
4. Dropping 5 files simultaneously: concurrency=3 means 3 process, 2 queue. All five complete eventually.
5. A worker chunk OOMing leaves a partial batch (chunk XLSXs in Outbox without consolidated). Operator can re-fire that specific chunk via webhook curl, and Consolidator completes the merge.
