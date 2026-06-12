# How to Trigger a Pipeline Run or Backfill a Meeting

Use this when you need to manually run the 10-step meeting pipeline for a specific Fireflies meeting — either because the webhook missed it, a bug caused incorrect output, or you want to replay it after a classifier or NLM fix.

## Prerequisites

- The `VM_API_SECRET` (ask Elman or find it in Bitwarden)
- The Cloudflare Access credentials (`CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`)
- The Fireflies meeting ID (visible in the Fireflies URL: `app.fireflies.ai/view/...::MEETING_ID`)
- An SSH tunnel or direct access to the VM (see `tooling/infra/CLAUDE.md` for tunnel setup)

---

## Trigger a normal pipeline run

This is equivalent to what the Windmill webhook does. Returns 202 immediately; the pipeline runs in the background. Errors surface in Telegram.

```bash
curl -X POST https://leads.jumpersapp.com/api/pipeline/run \
  -H "Authorization: Bearer $VM_API_SECRET" \
  -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"meeting_id": "MEETING_ID_HERE"}'
```

**Expected response:**
```json
{"status": "accepted", "meeting_id": "MEETING_ID_HERE"}
```

**Verification:** Watch Telegram for the pipeline completion or error notification. Or SSH to the VM and check the vm-api logs:

```bash
gcloud compute ssh paperclip-vm --tunnel-through-iap --zone=us-central1-f --project=paperclip-tribuai -- 'sudo journalctl -u vm-api -n 100 -f'
```

---

## Force-backfill a meeting that's already been processed

If a meeting is in `state.json._processed`, a normal run returns `{"status": "skipped", "reason": "already_processed"}`. Use `force: true` to bypass this check.

Force runs are synchronous — the response contains the full per-step result. Run one at a time.

```bash
curl -X POST https://leads.jumpersapp.com/api/pipeline/run \
  -H "Authorization: Bearer $VM_API_SECRET" \
  -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"meeting_id": "MEETING_ID_HERE", "force": true}'
```

**Expected response (success):**
```json
{
  "status": "completed",
  "meeting_id": "...",
  "title": "...",
  "category": "customer-discovery",
  "steps": {
    "fetch": {"status": "ok", "title": "..."},
    "classify_speakers": {"status": "ok", "external_speakers": [...], "internal_speakers": [...]},
    "classify_meeting": {"status": "ok", "category": "customer-discovery", "confidence": "high", "reasoning": "..."},
    "discovery_extraction": {"status": "ok"},
    "notebooklm_notebook": {"status": "ok", "notebook_id": "...", "is_new": false},
    "notebooklm_upload": {"status": "skipped", "reason": "already_uploaded"},
    "nlm_analysis": {"status": "ok", "novel_length": 1234},
    "email": {"status": "ok"},
    "mark_processed": {"status": "ok"},
    "hindsight": {"status": "ok"}
  }
}
```

`force: true` bypasses the `is_meeting_processed` check but does **not** bypass the `is_nlm_uploaded` check. If the transcript was already uploaded to NotebookLM, the upload step is skipped and only the analysis + email re-run.

> **Warning:** For `customer-discovery` meetings, `force: true` will re-run the novel-insights analysis and **send a duplicate email** to the external contact. If you want to replay without emailing, add `Internal:` to the start of the meeting title in Fireflies before force-running (this suppresses the email step while still running upload and analysis).

---

## Backfill multiple meetings

For bulk backfills, use the backfill runbook: `vm-api/docs/backfill-runbook.md`. It covers running a script loop over a list of meeting IDs and monitoring progress.

---

## Check which meetings have been processed

SSH to the VM and read `state.json`:

```bash
gcloud compute ssh paperclip-vm --tunnel-through-iap --zone=us-central1-f --project=paperclip-tribuai -- 'cat /home/elmanamador/automations/vm-api/state.json | python3 -m json.tool | grep -A5 "_processed"'
```

Or fetch a count:

```bash
gcloud compute ssh paperclip-vm --tunnel-through-iap --zone=us-central1-f --project=paperclip-tribuai -- 'python3 -c "import json; s=json.load(open(\"/home/elmanamador/automations/vm-api/state.json\")); print(f\"{len(s.get(\"_processed\",[]))} processed, {len(s.get(\"_nlm_uploaded\",[]))} NLM uploaded\")"'
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `{"status": "skipped", "reason": "already_processed"}` | Meeting is in `state.json._processed` | Add `"force": true` to the request |
| `{"status": "skipped", "reason": "in_flight"}` | Another run for this meeting is already in progress | Wait 5 minutes and retry |
| `401 Unauthorized` | Wrong `VM_API_SECRET` | Check Bitwarden |
| `403 Forbidden` | Wrong CF Access credentials | Check `CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET` |
| `classify_meeting: error` | Claude proxy is down | Check `GET /health/full`; SSH and restart `sudo systemctl restart claude-proxy` |
| `notebooklm_upload: error` | `nlm` CLI auth expired or notebook ID stale | SSH and run `nlm` manually to check auth; see backfill runbook |

---

## Related

- Backfill runbook: `vm-api/docs/backfill-runbook.md`
- VM API endpoints: `vm-api/README.md`
- Pipeline design: [explanation-pipeline-design.md](explanation-pipeline-design.md)
- SSH access: `tooling/infra/CLAUDE.md`
