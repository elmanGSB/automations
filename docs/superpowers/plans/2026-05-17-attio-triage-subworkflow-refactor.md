# Attio Triage v2 — Sub-workflow Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor Attio Triage v2 (`HrQEwEig7NgpcFvi`) so it processes large CSVs (612+ rows) without OOM crashes, using sub-workflows to bound per-chunk memory.

**Architecture:** Two n8n workflows connected via Execute Workflow node. `Triage-Main` orchestrates ingestion, chunks the deduped rows into batches of 100, calls `Triage-Worker` per chunk, collects enriched results, builds one consolidated XLSX. `Triage-Worker` runs the resolver + Attio + Hunter + Apollo enrichment for one chunk and returns the enriched rows.

**Tech Stack:** n8n Cloud (workflow `HrQEwEig7NgpcFvi`), n8n REST API + Python urllib for workflow JSON manipulation, claude-proxy on paperclip-vm (Anthropic-compatible endpoint at llm.jumpersapp.com), Attio API, Hunter API, Apollo API, Google Drive (Pipeline Inbox + Triage Outbox folders).

**Reference spec:** `/Users/elmanamador/coding/automations/docs/superpowers/specs/2026-05-17-attio-triage-split-and-queue-design.md`

---

## File map

| Path | Action |
|---|---|
| n8n workflow `HrQEwEig7NgpcFvi` (Triage-Main) | Refactor: delete resolver + Attio + Hunter + Apollo + Webhook nodes; add chunker + Execute Workflow call |
| n8n workflow `Triage-Worker` (new) | Create from scratch by lifting the deleted nodes |
| `/tmp/triage_backup_main_pre_refactor.json` | Backup of Triage-Main before any changes |
| `/tmp/triage_worker_build.py` | Python script that constructs Triage-Worker via REST API |
| `/tmp/triage_main_refactor.py` | Python script that refactors Triage-Main |
| `/tmp/triage_test_100row.csv` | Local test file: first 100 rows of registered distributors |
| `/tmp/triage_test_200row.csv` | Local test file: first 200 rows for concurrency probe |
| `/Users/elmanamador/coding/automations/docs/superpowers/plans/...` (this file) | Plan document |

## Conventions used throughout

- All Python patches use `urllib.request` (stdlib, no installs).
- `N8N_BASE = "https://broccolliai.app.n8n.cloud/api/v1"` ; `N8N_KEY` from `config/preflight.env`.
- Workflow API: GET `/workflows/<id>` returns full JSON; PUT `/workflows/<id>` with `{name, nodes, connections, settings}` replaces it (settings filtered to allowlist).
- After each PUT, the workflow's `active` flag may flip to false — must re-activate via POST `/workflows/<id>/activate`.
- Helper to source env: `set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a` before any `python3 ...` script that reads `$N8N_API_KEY`.

---

## Phase 0: Backup + ground truth

### Task 1: Snapshot current Triage-Main JSON

**Files:**
- Create: `/tmp/triage_backup_main_pre_refactor.json`

- [ ] **Step 1: Fetch and save**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
curl -sH "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/workflows/HrQEwEig7NgpcFvi" \
  > /tmp/triage_backup_main_pre_refactor.json
```

- [ ] **Step 2: Verify file is non-empty and valid JSON**

```bash
python3 -c "import json; d=json.load(open('/tmp/triage_backup_main_pre_refactor.json')); print(f\"name={d['name']}, nodes={len(d['nodes'])}, active={d['active']}\")"
```

Expected output: `name=Attio Triage v2, nodes=49, active=True` (node count may vary ±2 depending on intermediate state).

- [ ] **Step 3: Verify backup is readable later (sanity check)**

```bash
ls -lh /tmp/triage_backup_main_pre_refactor.json
```

Expected: file ≥50 KB.

---

## Phase 1: Build Triage-Worker (new, standalone)

### Task 2: Create empty Triage-Worker workflow with Execute Workflow Trigger

**Files:**
- Create: `/tmp/triage_worker_build.py`

- [ ] **Step 1: Write the build script (step 1 of 5 — create empty shell)**

```python
# /tmp/triage_worker_build.py
"""Build Triage-Worker workflow via n8n REST API.

Step 1: Create empty workflow with Execute Workflow Trigger only.
Subsequent steps in this script append more nodes; each step PUTs the full
state. Re-running the script is safe — it builds from scratch each time.
"""
import json
import os
import urllib.request
import uuid

N8N_BASE = "https://broccolliai.app.n8n.cloud/api/v1"
N8N_KEY = os.environ["N8N_API_KEY"]

def newnode(name, ntype, version, position, params, creds=None, opts=None):
    n = {"id": str(uuid.uuid4()), "name": name, "type": ntype,
         "typeVersion": version, "position": position, "parameters": params}
    if creds: n["credentials"] = creds
    if opts: n.update(opts)
    return n

# === Workflow shell ===
trigger = newnode(
    "Execute Workflow Trigger", "n8n-nodes-base.executeWorkflowTrigger", 1,
    [0, 0],
    {}
)

workflow = {
    "name": "Triage-Worker",
    "nodes": [trigger],
    "connections": {},
    "settings": {"executionOrder": "v1"}
}

# Create the workflow (no existing ID yet)
req = urllib.request.Request(
    f"{N8N_BASE}/workflows",
    data=json.dumps(workflow).encode(),
    method="POST",
    headers={"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"}
)
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
    worker_id = result["id"]
    print(f"Created Triage-Worker with ID: {worker_id}")
    print(f"View: https://broccolliai.app.n8n.cloud/workflow/{worker_id}")

# Save ID to a file for subsequent scripts to consume
with open('/tmp/triage_worker_id.txt', 'w') as f:
    f.write(worker_id)
```

- [ ] **Step 2: Run the build script**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
python3 /tmp/triage_worker_build.py
```

Expected output: `Created Triage-Worker with ID: <some-id>` and the file `/tmp/triage_worker_id.txt` exists.

- [ ] **Step 3: Verify in n8n UI**

Open `https://broccolliai.app.n8n.cloud/workflow/<worker_id>` (use the ID printed in step 2). Verify the workflow exists with one node: `Execute Workflow Trigger`. Workflow shows as inactive (that's expected; sub-workflows don't need to be active).

### Task 3: Lift resolver branch nodes into Triage-Worker

Lifts: `Has Domain?`, `Build Resolver Batches`, `AI: Resolve Domains via Web Search`, `Apply Resolutions`, `Merge Has-Domain + Resolved` from Triage-Main into the new Worker.

**Files:**
- Modify: `/tmp/triage_worker_build.py` (append second half)

- [ ] **Step 1: Append node-lift logic to the build script**

Edit `/tmp/triage_worker_build.py` and add the following at the end (after the existing `Created Triage-Worker...` print):

```python
# === Lift resolver branch nodes from Triage-Main ===
# Fetch current Triage-Main definition to copy node configs.
req2 = urllib.request.Request(
    f"{N8N_BASE}/workflows/HrQEwEig7NgpcFvi",
    headers={"X-N8N-API-KEY": N8N_KEY}
)
with urllib.request.urlopen(req2) as resp:
    main_wf = json.loads(resp.read())

RESOLVER_NODE_NAMES = [
    "Has Domain?",
    "Build Resolver Batches",
    "AI: Resolve Domains via Web Search",
    "Apply Resolutions",
    "Merge Has-Domain + Resolved",
]
ATTIO_NODE_NAMES = [
    "Attio: Find Company by Domain",
    "Classify Match Count",
    "In CRM with 1 match?",
    "Attio: Read Company Record",
    "Attio: Query People for Company",
    "Classify Engagement",
    "Pass-through Non-CRM Row",
    "Loop Companies",
]
BRANCH_D_NODE_NAMES = [
    "Is Branch D?",
    "Hunter: Domain Search",
    "Merge Hunter Results",
    "Hunter Returned Empty?",
    "Apollo: People Search",
    "Merge Apollo Results",
]

ALL_LIFTED = RESOLVER_NODE_NAMES + ATTIO_NODE_NAMES + BRANCH_D_NODE_NAMES

# Copy node defs verbatim
lifted_nodes = []
for n in main_wf['nodes']:
    if n['name'] in ALL_LIFTED:
        # Assign fresh UUID so n8n treats it as a new node
        n_copy = dict(n)
        n_copy['id'] = str(uuid.uuid4())
        lifted_nodes.append(n_copy)

print(f"Lifted {len(lifted_nodes)} nodes from Triage-Main")

# Append a "Return Enriched" set/code node — sub-workflow's last node's output IS its return value.
return_node = newnode(
    "Return Enriched", "n8n-nodes-base.code", 2, [3200, 0],
    {"jsCode": (
        "// Final node — passes items through. Sub-workflow's last node's output\n"
        "// is what Execute Workflow returns to the parent.\n"
        "return $input.all();\n"
    )}
)

# Update Triage-Worker JSON: trigger + lifted nodes + return node
all_nodes = [trigger] + lifted_nodes + [return_node]

# Copy connections too — only those internal to the lifted node set
lifted_names = set(n['name'] for n in lifted_nodes)
new_connections = {}
for src_name, conn in main_wf.get('connections', {}).items():
    if src_name not in lifted_names:
        continue
    # Filter destinations to only those that are also lifted
    new_conn = {"main": []}
    for branch in conn.get('main', []):
        new_branch = [d for d in branch if d['node'] in lifted_names]
        new_conn['main'].append(new_branch)
    new_connections[src_name] = new_conn

# Wire Execute Workflow Trigger → Has Domain?
new_connections["Execute Workflow Trigger"] = {
    "main": [[{"node": "Has Domain?", "type": "main", "index": 0}]]
}

# Wire the last enrichment node into Return Enriched.
# Discovery: the existing Merge Apollo Results is the convergence point for Branch D;
# Loop Companies feeds outputs back via Pass-through Non-CRM Row + Classify Engagement.
# We'll wire BOTH terminal points into Return Enriched.
# - Classify Engagement → Return Enriched (in-CRM rows)
# - Merge Apollo Results → Return Enriched (Branch D rows)
# - Pass-through Non-CRM Row → Return Enriched (other non-CRM cases)
for terminal in ["Classify Engagement", "Merge Apollo Results", "Pass-through Non-CRM Row"]:
    if terminal in new_connections:
        new_connections[terminal] = {"main": [[{"node": "Return Enriched", "type": "main", "index": 0}]]}
    else:
        new_connections[terminal] = {"main": [[{"node": "Return Enriched", "type": "main", "index": 0}]]}

workflow_body = {
    "name": "Triage-Worker",
    "nodes": all_nodes,
    "connections": new_connections,
    "settings": {"executionOrder": "v1"}
}

# PUT to update the workflow we just created
put_req = urllib.request.Request(
    f"{N8N_BASE}/workflows/{worker_id}",
    data=json.dumps(workflow_body).encode(),
    method="PUT",
    headers={"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"}
)
with urllib.request.urlopen(put_req) as resp:
    result = json.loads(resp.read())
    print(f"Triage-Worker updated: {len(result['nodes'])} nodes")
```

- [ ] **Step 2: Re-run the build script**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
python3 /tmp/triage_worker_build.py
```

Expected output:
```
Created Triage-Worker with ID: <new-id-different-from-before>
Lifted 19 nodes from Triage-Main
Triage-Worker updated: 21 nodes
```

(Note: the script creates a NEW workflow each time. Old run's workflow stays as a leftover and should be archived in step 3.)

- [ ] **Step 3: Archive any duplicate Triage-Worker workflows from prior runs**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
# List all workflows named Triage-Worker
curl -sH "X-N8N-API-KEY: $N8N_API_KEY" \
  "$N8N_BASE_URL/workflows?name=Triage-Worker" | jq '.data[] | {id, name, active, isArchived}'
```

Keep ONLY the ID in `/tmp/triage_worker_id.txt`. Archive others via:
```bash
# For each duplicate ID:
curl -sX POST -H "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/workflows/<dup-id>/archive"
```

- [ ] **Step 4: Verify in UI**

Open the Triage-Worker URL printed in Task 2 Step 2. Expected node count: 21 (1 trigger + 19 lifted + 1 return). Visually verify the connections look reasonable (will likely need manual cleanup in the next task).

### Task 4: Manually clean up Triage-Worker connections in the n8n UI

The Python lift in Task 3 copies connection definitions verbatim but those connections may reference nodes that didn't get lifted (e.g. `Merge Has-Domain + Resolved` was wired to `Loop Companies` in Main, but `Loop Companies` IS lifted — that should work; verify). Some connections may be missing or dangling.

**Files:** none (UI work only)

- [ ] **Step 1: Open Triage-Worker in the n8n UI**

URL: `https://broccolliai.app.n8n.cloud/workflow/<worker_id>`

- [ ] **Step 2: Verify these connections exist (rewire manually if missing)**

Required connection graph:
```
Execute Workflow Trigger
  → Has Domain?
      [TRUE]  → Merge Has-Domain + Resolved [input 0]
      [FALSE] → Build Resolver Batches → AI: Resolve Domains via Web Search → Apply Resolutions → Merge Has-Domain + Resolved [input 1]
  → Loop Companies
      → Attio: Find Company by Domain → Classify Match Count → In CRM with 1 match?
          [YES] → Attio: Read Company Record → Attio: Query People for Company → Classify Engagement → Return Enriched
          [NO]  → Pass-through Non-CRM Row → Is Branch D?
              [YES] → Hunter: Domain Search → Merge Hunter Results → Hunter Returned Empty?
                  [YES] → Apollo: People Search → Merge Apollo Results → Return Enriched
                  [NO]  → Merge Apollo Results → Return Enriched
              [NO]  → Return Enriched
```

- [ ] **Step 3: Save the workflow**

Press Cmd+S in the UI. Verify "Saved" indicator appears.

- [ ] **Step 4: Re-fetch the saved JSON and confirm structure**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
WORKER_ID=$(cat /tmp/triage_worker_id.txt)
curl -sH "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/workflows/$WORKER_ID" \
  > /tmp/triage_worker_current.json
python3 -c "
import json
d = json.load(open('/tmp/triage_worker_current.json'))
print(f'Nodes: {len(d[\"nodes\"])}')
print(f'Connections: {len(d[\"connections\"])}')
# Verify the trigger node has the right out-connection
assert 'Execute Workflow Trigger' in d['connections'], 'trigger has no outgoing connection'
print('Trigger out:', d['connections']['Execute Workflow Trigger'])
"
```

Expected: `Trigger out: {'main': [[{'node': 'Has Domain?', 'type': 'main', 'index': 0}]]}`

### Task 5: Set Triage-Worker concurrency to 3

**Files:** none (UI work only)

- [ ] **Step 1: Open Triage-Worker in the n8n UI**

URL: `https://broccolliai.app.n8n.cloud/workflow/<worker_id>`

- [ ] **Step 2: Open Settings**

Click the gear icon → Workflow Settings.

- [ ] **Step 3: Set concurrency**

Find "Concurrency" / "Worker concurrency" / similar. Set to `3`. Save.

(If n8n Cloud's plan doesn't expose this setting at the workflow level, skip — concurrency will default to whatever the account allows, and the parent's sequential SplitInBatches loop naturally serializes.)

### Task 6: Test Triage-Worker in isolation via pin-data execution

**Files:**
- Create: `/tmp/triage_worker_pin.json` (test input data)

- [ ] **Step 1: Build a 5-row test pin payload**

```bash
cat > /tmp/triage_worker_pin.json <<'EOF'
{
  "Execute Workflow Trigger": [
    {"json": {"name": "Nulaid Foods Inc", "city": "Ripon", "domain": "", "linkedin_url": ""}},
    {"json": {"name": "Costco Depot #961", "city": "Mira Loma", "domain": "", "linkedin_url": ""}},
    {"json": {"name": "WinCo Foods", "city": "Modesto", "domain": "", "linkedin_url": ""}},
    {"json": {"name": "Sysco Riverside", "city": "Riverside", "domain": "", "linkedin_url": ""}},
    {"json": {"name": "Gemperle Family Farms", "city": "Turlock", "domain": "", "linkedin_url": ""}}
  ]
}
EOF
```

- [ ] **Step 2: Execute Triage-Worker with pinned data via n8n UI**

In the n8n UI on Triage-Worker: click the `Execute Workflow Trigger` node, click "Test step" / "Set Pinned Data", paste the JSON above. Then click "Test workflow" or "Execute Workflow".

(If the UI doesn't expose pin-data well, alternative: open `Execute Workflow Trigger` node → switch to "test" mode → click "Listen" → manually invoke via curl with the items.)

- [ ] **Step 3: Verify the output of `Return Enriched`**

Click the `Return Enriched` node. It should show 5 items, each enriched with `domain`, `branch`, `in_crm`, `recommended_action`. Specifically:

```
Costco Depot #961 → costco.com (Branch D)
Nulaid Foods Inc → nulaid.com (Branch D)
Sysco Riverside → sysco.com (likely Branch A if in CRM)
WinCo Foods → wincofoods.com
Gemperle Family Farms → gemperle.com
```

If any of these come back with empty domain, investigate the resolver branch wiring.

- [ ] **Step 4: Document the worker_id and node count for the next phase**

```bash
WORKER_ID=$(cat /tmp/triage_worker_id.txt)
echo "Triage-Worker ID: $WORKER_ID — pin-data test passed"
```

---

## Phase 2: Refactor Triage-Main

### Task 7: Compose the Triage-Main refactor patch

**Files:**
- Create: `/tmp/triage_main_refactor.py`

- [ ] **Step 1: Write the refactor script**

```python
# /tmp/triage_main_refactor.py
"""Refactor Triage-Main: remove the resolver + Attio + Hunter + Apollo +
Webhook nodes (now in Triage-Worker), insert SplitInBatches + Execute Workflow.
"""
import json
import os
import urllib.request
import uuid

N8N_BASE = "https://broccolliai.app.n8n.cloud/api/v1"
N8N_KEY = os.environ["N8N_API_KEY"]
MAIN_ID = "HrQEwEig7NgpcFvi"

with open('/tmp/triage_worker_id.txt') as f:
    WORKER_ID = f.read().strip()
print(f"Calling Triage-Worker ID: {WORKER_ID}")

# Fetch current state
req = urllib.request.Request(f"{N8N_BASE}/workflows/{MAIN_ID}", headers={"X-N8N-API-KEY": N8N_KEY})
with urllib.request.urlopen(req) as resp:
    wf = json.loads(resp.read())

# === Delete nodes that have moved to Triage-Worker ===
TO_DELETE = {
    # Resolver
    "Has Domain?", "Build Resolver Batches", "AI: Resolve Domains via Web Search",
    "Apply Resolutions", "Merge Has-Domain + Resolved",
    # Attio enrichment
    "Attio: Find Company by Domain", "Classify Match Count", "In CRM with 1 match?",
    "Attio: Read Company Record", "Attio: Query People for Company", "Classify Engagement",
    "Pass-through Non-CRM Row", "Loop Companies",
    # Branch D enrichment
    "Is Branch D?", "Hunter: Domain Search", "Merge Hunter Results",
    "Hunter Returned Empty?", "Apollo: People Search", "Merge Apollo Results",
    # Webhook (no longer needed)
    "Webhook: Manual Trigger", "Webhook to File Ref",
}
wf['nodes'] = [n for n in wf['nodes'] if n['name'] not in TO_DELETE]
for name in list(wf['connections'].keys()):
    if name in TO_DELETE:
        del wf['connections'][name]
# Also clean up connections that REFERENCE deleted nodes
for src, conn in wf['connections'].items():
    new_main = []
    for branch in conn.get('main', []):
        new_branch = [d for d in branch if d['node'] not in TO_DELETE]
        new_main.append(new_branch)
    conn['main'] = new_main

print(f"After delete: {len(wf['nodes'])} nodes remain")

# === Insert Chunk Into Batches + Execute Workflow + Flatten Output ===
def newnode(name, ntype, version, position, params, opts=None):
    n = {"id": str(uuid.uuid4()), "name": name, "type": ntype,
         "typeVersion": version, "position": position, "parameters": params}
    if opts: n.update(opts)
    return n

chunk_node = newnode(
    "Chunk Into Batches", "n8n-nodes-base.code", 2, [1500, 200],
    {"jsCode": (
        "// Group input rows into batches of CHUNK_SIZE; emit one n8n item per\n"
        "// batch. Each item's json.batch_rows is an array of original rows.\n"
        "// Used in conjunction with Execute Workflow (Run Once For Each Item),\n"
        "// so the Worker is invoked once per batch with the rows as a payload.\n"
        "const CHUNK_SIZE = 100;\n"
        "const items = $input.all();\n"
        "const batches = [];\n"
        "for (let i = 0; i < items.length; i += CHUNK_SIZE) {\n"
        "  const slice = items.slice(i, i + CHUNK_SIZE).map(it => it.json);\n"
        "  batches.push({ json: {\n"
        "    batch_index: Math.floor(i / CHUNK_SIZE),\n"
        "    batch_rows: slice,\n"
        "    total_batches: Math.ceil(items.length / CHUNK_SIZE),\n"
        "    total_rows: items.length\n"
        "  }});\n"
        "}\n"
        "return batches.length ? batches : [{ json: { batch_index: 0, batch_rows: [], total_batches: 1, total_rows: 0 } }];\n"
    )}
)

# Execute Workflow node — version 1.x; runs once per input item
exec_worker = newnode(
    "Execute Worker per Batch", "n8n-nodes-base.executeWorkflow", 1.1, [1720, 200],
    {
        "source": "database",
        "workflowId": {"__rl": True, "mode": "id", "value": WORKER_ID},
        "mode": "runOnceForEachItem",
        "options": {}
    }
)

# Worker output unwrap — Worker returns N enriched items per call;
# Execute Workflow concatenates outputs across all input items.
# Verify the shape, no transformation needed beyond passing through.
unwrap = newnode(
    "Collect Worker Outputs", "n8n-nodes-base.code", 2, [1940, 200],
    {"jsCode": (
        "// Pass through enriched rows from Execute Worker per Batch.\n"
        "// Each n8n item is one enriched row, ready for Build Companies Output.\n"
        "return $input.all();\n"
    )}
)

wf['nodes'].extend([chunk_node, exec_worker, unwrap])

# Wire: Dedup Companies → Chunk Into Batches → Execute Worker per Batch → Collect → Build Companies Output
wf['connections']['Dedup Companies'] = {"main": [[
    {"node": "Chunk Into Batches", "type": "main", "index": 0}
]]}
wf['connections']['Chunk Into Batches'] = {"main": [[
    {"node": "Execute Worker per Batch", "type": "main", "index": 0}
]]}
wf['connections']['Execute Worker per Batch'] = {"main": [[
    {"node": "Collect Worker Outputs", "type": "main", "index": 0}
]]}
wf['connections']['Collect Worker Outputs'] = {"main": [[
    {"node": "Build Companies Output", "type": "main", "index": 0}
]]}

# === PUT updated workflow ===
allowed = {"executionOrder","saveDataErrorExecution","saveDataSuccessExecution",
           "saveManualExecutions","saveExecutionProgress","timezone"}
settings = {k:v for k,v in wf.get("settings",{}).items() if k in allowed}
body = {"name": wf["name"], "nodes": wf["nodes"], "connections": wf["connections"], "settings": settings}
data = json.dumps(body).encode()
put_req = urllib.request.Request(
    f"{N8N_BASE}/workflows/{MAIN_ID}",
    data=data,
    method="PUT",
    headers={"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"}
)
with urllib.request.urlopen(put_req) as resp:
    result = json.loads(resp.read())
    print(f"Triage-Main refactored: {len(result['nodes'])} nodes")

# Save snapshot
with open('/Users/elmanamador/coding/n8n-automations/workflows/attio-triage-v2.json', 'w') as f:
    json.dump(body, f, indent=2)
print("Local snapshot written to workflows/attio-triage-v2.json")
```

- [ ] **Step 2: Run the refactor script**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
python3 /tmp/triage_main_refactor.py
```

Expected output:
```
Calling Triage-Worker ID: <worker-id>
After delete: ~28 nodes remain
Triage-Main refactored: ~31 nodes
Local snapshot written to workflows/attio-triage-v2.json
```

- [ ] **Step 3: Re-activate Triage-Main if it became inactive after PUT**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
curl -sX POST -H "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/workflows/HrQEwEig7NgpcFvi/activate" \
  | jq '{active, updatedAt}'
```

Expected: `{"active": true, ...}`

### Task 8: Verify Triage-Main connection graph

**Files:** none (UI + API verification)

- [ ] **Step 1: Open Triage-Main in the n8n UI**

URL: `https://broccolliai.app.n8n.cloud/workflow/HrQEwEig7NgpcFvi`

- [ ] **Step 2: Trace the data flow visually**

Expected graph (left to right):
```
GDrive Trigger → GDrive: Download File → Compute SHA256
  → Manifest: Lookup → Decide Claim → Should Process?
      [false] → Log Skip (terminal)
      [true]  → Manifest: Claim → Restore Binary → Detect File Format
                → Extract: CSV Companies (or Extract: Companies sheet)
                → Merge Input Rows → Dedup Companies
                → Chunk Into Batches → Execute Worker per Batch → Collect Worker Outputs
                → Build Companies Output → Convert to XLSX (Companies)
                → Upload Output to Triage Outbox → (parallel: Contacts pipeline)
                → Merge Output Branches → Manifest: Mark Success → Move Input to Processed
```

If any node has dangling input/output (e.g. `Build Companies Output` has no input), use the n8n UI to wire manually then save.

- [ ] **Step 3: Verify via API**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
curl -sH "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/workflows/HrQEwEig7NgpcFvi" \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
# Verify the new wiring
assert 'Chunk Into Batches' in d['connections'], 'Chunk Into Batches missing'
assert 'Execute Worker per Batch' in d['connections'], 'Execute Worker per Batch missing'
# Verify no orphans
expected_chain = ['Dedup Companies', 'Chunk Into Batches', 'Execute Worker per Batch', 'Collect Worker Outputs']
for n in expected_chain:
    if n != expected_chain[-1]:
        assert n in d['connections'], f'{n} has no outgoing connection'
print('Chain verified:', ' → '.join(expected_chain), '→ Build Companies Output')
"
```

Expected: `Chain verified: Dedup Companies → Chunk Into Batches → ...`

---

## Phase 3: End-to-end verification

### Task 9: 5-row smoke test (smallest possible)

**Files:**
- Create: `/tmp/triage_smoke_5row.csv`

- [ ] **Step 1: Build the smoke test file**

```bash
cat > /tmp/triage_smoke_5row.csv <<'EOF'
Business Name,city
Nulaid Foods Inc,Ripon
Costco Depot #961,Mira Loma
WinCo Foods,Modesto
Sysco Riverside,Riverside
Gemperle Family Farms,Turlock
EOF
shasum -a 256 /tmp/triage_smoke_5row.csv
```

Expected: a SHA256 hash (note it for manifest debugging if needed).

- [ ] **Step 2: Upload to Pipeline Inbox via GDrive MCP**

Use the `mcp__claude_ai_Google_Drive__create_file` tool with:
- `title`: `smoke-5row-<timestamp>.csv`
- `parentId`: `1HjQBY1nRlyB4pVH-hjjOInoBJrzt6n5k` (Pipeline Inbox)
- `contentMimeType`: `text/csv`
- `disableConversionToGoogleType`: `true`
- `textContent`: paste the CSV content from Step 1.

Note the returned `id`.

- [ ] **Step 3: Wait for trigger fire (max 4 min)**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
LAST=$(curl -sH "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/executions?workflowId=HrQEwEig7NgpcFvi&limit=1" | jq -r '.data[0].id')
echo "Last exec before drop: $LAST"
for i in $(seq 1 12); do
  NEW=$(curl -sH "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/executions?workflowId=HrQEwEig7NgpcFvi&limit=1" | jq -r '.data[0].id')
  if [ "$NEW" != "$LAST" ]; then echo "[$(date -u +%H:%M:%S)] new exec: $NEW"; break; fi
  echo "[$(date -u +%H:%M:%S)] waiting..."
  sleep 20
done
```

- [ ] **Step 4: Watch the new execution to completion**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
EXEC_ID=$NEW
until STATUS=$(curl -sH "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/executions/$EXEC_ID" | jq -r '.status') && [ "$STATUS" != "running" ] && [ "$STATUS" != "new" ]; do
  echo "[$(date -u +%H:%M:%S)] $EXEC_ID: $STATUS"
  sleep 30
done
echo "$EXEC_ID finished: $STATUS"
```

- [ ] **Step 5: Verify the output XLSX in Triage Outbox**

Use `mcp__claude_ai_Google_Drive__search_files` with query `parentId = '1nTWcoZfmYcNXaG-OVbxp6PB6g0ABh3UT' and title contains 'smoke-5row'`. Confirm a single XLSX file landed. Note the file ID.

- [ ] **Step 6: Verify the resolver branch fired inside Triage-Worker**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
# Get the Execute Worker per Batch sub-execution from the parent exec
curl -sH "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/executions/$EXEC_ID?includeData=true" \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
runs = d.get('data', {}).get('resultData', {}).get('runData', {})
print('Nodes that ran:', list(runs.keys()))
exec_worker = runs.get('Execute Worker per Batch', [])
print(f'Execute Worker per Batch invocations: {len(exec_worker)}')
"
```

Expected: `Execute Worker per Batch invocations: 1` (one batch since 5 rows < 100).

### Task 10: 100-row test (full chunking, single batch)

**Files:**
- Create: `/tmp/triage_test_100row.csv`

- [ ] **Step 1: Build the 100-row test file from existing CDFA data**

```bash
head -101 /Users/elmanamador/Downloads/Registered_Distributors.csv > /tmp/triage_test_100row.csv
wc -l /tmp/triage_test_100row.csv
shasum -a 256 /tmp/triage_test_100row.csv
```

Expected: 101 lines (1 header + 100 data rows).

- [ ] **Step 2: Upload to Pipeline Inbox**

Use `mcp__claude_ai_Google_Drive__create_file` with the file content. Title: `100row-test-<timestamp>.csv`. (Note: textContent param accepts the full CSV string; 100-row file is ~7 KB which is well within tool limits.)

- [ ] **Step 3: Wait for completion and capture exec ID**

Use the polling pattern from Task 9 step 4. Note `EXEC_ID` and total wall time.

Expected wall time: ~12 min.

- [ ] **Step 4: Verify the scorecard**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
curl -sH "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/executions/$EXEC_ID?includeData=true" \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
runs = d.get('data', {}).get('resultData', {}).get('runData', {})
# Collect Worker Outputs output should have all 100 enriched rows
co = runs.get('Collect Worker Outputs', [{}])[0]
items = co.get('data', {}).get('main', [[]])[0]
total = len(items)
with_domain = sum(1 for it in items if it.get('json',{}).get('domain'))
in_crm = sum(1 for it in items if it.get('json',{}).get('in_crm') == True or it.get('json',{}).get('in_crm') == 'yes')
print(f'Total rows: {total}')
print(f'With domain: {with_domain} ({100*with_domain/max(1,total):.1f}%)')
print(f'In CRM: {in_crm}')
"
```

Baseline from exec 465 (manual chunking): 100 rows, 95 domains (95%), 16 in CRM. New result should match within ±5 rows.

### Task 11: 612-row production test

**Files:** none

- [ ] **Step 1: Verify the full file is in Pipeline Inbox**

The file `Registered_Distributors_run.csv` (ID `1G99RqUZWYLt3gclmN3oNwTWGYJqH_Irp`) should already be in Pipeline Inbox from prior work. If not, copy from another GDrive location:

```
mcp__claude_ai_Google_Drive__copy_file
fileId: 1G99RqUZWYLt3gclmN3oNwTWGYJqH_Irp
parentId: 1HjQBY1nRlyB4pVH-hjjOInoBJrzt6n5k
title: 612row-prod-test-<timestamp>.csv
```

- [ ] **Step 2: Wait for trigger fire**

(GDrive trigger polls every minute; expect ~1-3 min)

- [ ] **Step 3: Watch with periodic status reports**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
EXEC_ID=<id-from-step-2>
START=$(date +%s)
LAST=0
until STATUS=$(curl -sH "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/executions/$EXEC_ID" | jq -r '.status') && [ "$STATUS" != "running" ] && [ "$STATUS" != "new" ]; do
  EL=$(($(date +%s) - START))
  if [ $((EL - LAST)) -ge 300 ]; then
    printf "[%dm] %s: %s\n" $((EL/60)) "$EXEC_ID" "$STATUS"
    LAST=$EL
  fi
  sleep 60
done
EL=$(($(date +%s) - START))
echo "Finished: $STATUS — ${EL}s ($((EL/60))m)"
```

Expected: completes in ≤55 min (DECISION POINT: if it crashes/times out, see Task 12 fallback).

- [ ] **Step 4: Verify scorecard matches baseline**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
curl -sH "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/executions/$EXEC_ID?includeData=true" -o /tmp/exec612.json
python3 <<'PY'
import json
d = json.load(open('/tmp/exec612.json'))
runs = d.get('data', {}).get('resultData', {}).get('runData', {})
co = runs.get('Collect Worker Outputs', [{}])[0]
items = co.get('data', {}).get('main', [[]])[0]
total = len(items)
with_domain = sum(1 for it in items if it.get('json',{}).get('domain'))
in_crm = sum(1 for it in items if it.get('json',{}).get('in_crm') in (True, 'yes'))
actions = {}
for it in items:
    a = it.get('json',{}).get('recommended_action','?')
    actions[a] = actions.get(a, 0) + 1
print(f'Total rows: {total}')
print(f'With domain: {with_domain} ({100*with_domain/max(1,total):.1f}%) — baseline: 535 (87.4%)')
print(f'In CRM: {in_crm} — baseline: 43')
print()
print('Actions:')
for a, c in sorted(actions.items(), key=lambda x: -x[1]):
    print(f'  {a:35s} {c:4d}')
PY
```

Expected (matching exec 465+471+472+473+474+475 baseline):
- Total rows: 612 (±5)
- With domain: 535 (±10)
- In CRM: 43 (±2)

Any larger discrepancy: investigate before declaring done.

- [ ] **Step 5: Verify exactly one XLSX in Triage Outbox for this run**

Use GDrive search by recent createdTime. Expected: one file matching `<input-name>.xlsx` (no chunk pattern files).

### Task 12: Fallback if 612-row test exceeds 1h cap

This task only runs if Task 11 fails with `WorkflowCrashedError`. If Task 11 succeeded, mark this task SKIPPED.

**Files:** none

- [ ] **Step 1: Document the failure mode**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
curl -sH "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/executions/<failed-exec-id>?includeData=true" \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
err = d.get('data', {}).get('resultData', {}).get('error', {})
print('Error:', err.get('message', '')[:200])
print('Last node:', d.get('data', {}).get('resultData', {}).get('lastNodeExecuted', '?'))
"
```

- [ ] **Step 2: Apply per-chunk Upload Output workaround**

If the parent ran out of time, the most likely fix is moving `Upload Output to Triage Outbox` INTO `Triage-Worker` so each chunk uploads its own XLSX. This means the parent doesn't hold all 612 enriched rows at once.

This is the code-simplicity reviewer's recommendation. Implementation: open Triage-Worker, add the Build Companies Output + Convert to XLSX (Companies) + Upload Output to Triage Outbox at the END of the worker. Remove them from Triage-Main (Triage-Main becomes "trigger + dispatch", no consolidation).

Then add a separate one-off Python step at run-end to merge the chunk XLSXs into a single output (use the same merge code we ran for exec 465+).

(This task is intentionally light — if you hit it, the spec needs revision, not just implementation.)

---

## Phase 4: Cleanup + commit

### Task 13: Update local workflow snapshot

**Files:**
- Modify: `/Users/elmanamador/coding/n8n-automations/workflows/attio-triage-v2.json`
- Create: `/Users/elmanamador/coding/n8n-automations/workflows/triage-worker.json`

- [ ] **Step 1: Snapshot both workflows**

```bash
set -a && source /Users/elmanamador/coding/n8n-automations/config/preflight.env && set +a
WORKER_ID=$(cat /tmp/triage_worker_id.txt)
curl -sH "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/workflows/HrQEwEig7NgpcFvi" \
  | python3 -m json.tool > /Users/elmanamador/coding/n8n-automations/workflows/attio-triage-v2.json
curl -sH "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_BASE_URL/workflows/$WORKER_ID" \
  | python3 -m json.tool > /Users/elmanamador/coding/n8n-automations/workflows/triage-worker.json
ls -lh /Users/elmanamador/coding/n8n-automations/workflows/
```

- [ ] **Step 2: Commit snapshots (if /Users/elmanamador/coding/n8n-automations becomes a git repo)**

The n8n-automations directory is not currently a git repo. If you want version-tracking, initialize:
```bash
cd /Users/elmanamador/coding/n8n-automations && git init && git add . && git commit -m "Initial snapshot post-refactor"
```

(Otherwise, the snapshots serve as recovery artifacts on local disk.)

### Task 14: Mark the spec as Implemented

**Files:**
- Modify: `/Users/elmanamador/coding/automations/docs/superpowers/specs/2026-05-17-attio-triage-split-and-queue-design.md`

- [ ] **Step 1: Update the spec's Status line**

```bash
cd /Users/elmanamador/coding/automations
sed -i '' 's/\*\*Status:\*\* Design — pending review/**Status:** Implemented 2026-05-17/' \
  docs/superpowers/specs/2026-05-17-attio-triage-split-and-queue-design.md
grep "Status:" docs/superpowers/specs/2026-05-17-attio-triage-split-and-queue-design.md
```

Expected: `**Status:** Implemented 2026-05-17`

- [ ] **Step 2: Commit on the spec branch**

```bash
cd /Users/elmanamador/coding/automations && \
  git add docs/superpowers/specs/2026-05-17-attio-triage-split-and-queue-design.md && \
  git commit -m "spec: mark triage refactor as implemented"
```

- [ ] **Step 3: Push the branch + open PR**

```bash
cd /Users/elmanamador/coding/automations && git push -u origin spec/triage-split-and-queue
gh pr create --title "docs: Attio Triage sub-workflow refactor (spec + plan)" --body "$(cat <<'EOF'
## Summary

- Spec: `docs/superpowers/specs/2026-05-17-attio-triage-split-and-queue-design.md` (designed after multi-reviewer feedback)
- Plan: `docs/superpowers/plans/2026-05-17-attio-triage-subworkflow-refactor.md`

## Implementation result

- Triage-Main refactored to use SplitInBatches + Execute Workflow
- Triage-Worker workflow created
- 612-row file processes end-to-end (results pending Phase 3 test)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

(Inline check against the spec — no spec gaps found, but a few notes:)

- **Spec mentions Phase 2.5 concurrency test** — captured in Task 11 step 3 (wall time observation; if ~25 min then parallelism is working, if ~70 min then sequential as predicted).
- **Spec says Triage-Worker concurrency = 3** — Task 5 covers this (UI step; n8n cloud may or may not expose it).
- **Spec acceptance criteria 1-7** map to Tasks 6 (Worker isolation), 10 (100-row e2e), 11 (612-row baseline match), 11 step 5 (no chunk XLSX files), Task 12 (multi-file scenario — note: NOT in core plan; deferred to ad-hoc operator validation).
- **Spec says "no new Data Tables"** — verified; plan creates zero new tables.
- **Acceptance criterion #5 (multi-file simultaneous drop)** — not directly tested in this plan because it would require synchronized GDrive uploads. The architecture supports it by virtue of Triage-Worker's concurrency=3 setting. Mark as "spot-check after Phase 3 passes."
