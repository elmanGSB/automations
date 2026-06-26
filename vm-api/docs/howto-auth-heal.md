# How to handle Claude credential expiry

## Symptoms

A pipeline run returns:

```json
{"steps": {"classify_meeting": {"status": "error", "error": "auth_expired_no_refresh"}}}
```

Or the VM logs show:

```
WARNING  Claude auth expired for meeting <id> — refreshing credentials and retrying
ERROR    Secret Manager pull failed (rc=1): ...
```

If the auto-heal succeeds, the run continues normally and no action is needed — you'll see `classify_meeting_auth_refreshed: {status: ok}` in the step results.

---

## What the auto-heal does

When `classify_meeting` gets HTTP 401 from claude-proxy, `pipeline_runner` catches it and calls `_refresh_claude_credentials()`:

1. Pulls the latest credential version from GCP Secret Manager: `claude-code-credentials` in project `paperclip-tribuai`.
2. Checks that `gcloud` exited successfully (non-zero → logs error and aborts refresh).
3. Overwrites `~/.claude/.credentials.json` on the VM with the new token.
4. Retries `classify_meeting` once.

---

## Manual intervention: re-login on the VM

The auto-heal only works when Secret Manager has a fresh token. If credentials have been expired for a while, you need to re-login and push new creds.

**Step 1 — SSH into the VM and re-authenticate:**

```bash
gcloud compute ssh paperclip-vm --tunnel-through-iap \
  --zone=us-central1-f --project=paperclip-tribuai
claude  # follow the OAuth prompts in the terminal
```

**Step 2 — Push the new credentials to Secret Manager:**

```bash
# On the VM, after the claude login completes:
gcloud secrets versions add claude-code-credentials \
  --data-file=/home/elmanamador/.claude/.credentials.json \
  --project=paperclip-tribuai
```

Future auto-heal cycles will now pull this fresh version.

---

## Manual intervention: push from a local machine

If you've recently re-authenticated Claude locally, you can push local credentials directly:

```bash
# On your laptop:
gcloud secrets versions add claude-code-credentials \
  --data-file=~/.claude/.credentials.json \
  --project=paperclip-tribuai

# Optional: push to VM directly and restart so it picks up the new file immediately:
gcloud compute scp ~/.claude/.credentials.json \
  paperclip-vm:/home/elmanamador/.claude/.credentials.json \
  --tunnel-through-iap --zone=us-central1-f --project=paperclip-tribuai
gcloud compute ssh paperclip-vm --tunnel-through-iap --zone=us-central1-f --project=paperclip-tribuai \
  -- 'sudo systemctl restart vm-api'
```

---

## Replaying failed meetings

After credentials are refreshed, replay meetings that returned `auth_expired_no_refresh`:

```bash
# On the VM (auth-expired meetings are NOT in _processed — they failed at step 3):
SECRET=$(grep '^VM_API_SECRET=' /home/elmanamador/automations/vm-api/.env | cut -d= -f2-)

curl -X POST http://127.0.0.1:3101/api/pipeline/run \
  -H "Authorization: Bearer $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"meeting_id": "<id>", "force": false}'
```

Use `force: false` — auth failures happen at step 3 (classify_meeting), before `mark_meeting_processed` at step 9. The meeting is not in `_processed` and will run normally without `force`.

If you need to replay a meeting that is already in `_processed` (rare — would require a partial pipeline success followed by a later auth failure), use `force: true`. See the [backfill runbook](backfill-runbook.md) for batch replay.
