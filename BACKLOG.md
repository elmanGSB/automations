# Backlog — Future Improvements

Running list of known improvements deferred from in-flight fixes. Add to it when you ship a quick fix and want to capture the elegant version for later.

## Migrate Fireflies → Windmill webhook (replace direct VM call)

**Status:** Open — deferred from PR fixing 401s on `/webhook/fireflies` (2026-04-24).

**Context.** Today Fireflies POSTs directly to `https://jumpersapp.com/webhook/fireflies`, which Caddy proxies to VM API. PR fix/fireflies-direct-webhook-auth restored this path by removing a stray Bearer-token check and enforcing HMAC signature verification instead. That works, but it walks back from the architecture chosen in PR #3 (`feat/windmill-pipeline-migration`) where Windmill is the orchestrator.

**Goal.** Point Fireflies at the Windmill webhook URL so every meeting becomes a clickable job in Windmill, with retry/branching/scheduling primitives and the existing `alert_on_failure` Telegram step. Then the legacy `/webhook/fireflies` endpoint on VM API can be deleted.

**Steps.**
1. Fix the rotting Windmill workspace first — do **not** stack new dependence on a sick orchestrator:
   - Restore `u/admin/telegram_chat_id` Windmill variable (currently missing — that's why every `health_check` job has been failing for 2+ days).
   - Confirm the `health_check` flow runs green for 24h.
2. In Windmill, copy the webhook URL for the `f/discovery/fireflies_webhook` flow (it embeds an API token — treat as a secret).
3. In Fireflies → Integrations → Webhooks, change the URL from `https://jumpersapp.com/webhook/fireflies` to the Windmill URL. Leave the Signing Secret field — Windmill doesn't verify it; the Bearer token in the URL is the auth.
4. Send a test webhook from the Fireflies dashboard. Verify a `flow` job appears in Windmill and reaches the `forward_to_vm_api` step.
5. After 48h of clean operation, delete the legacy VM endpoint:
   - Remove the `@app.post("/webhook/fireflies")` route from `vm-api/main.py`.
   - Remove `FIREFLIES_WEBHOOK_SECRET` from the VM `.env`.
   - Remove `_verify_fireflies_signature` and the auth tests scoped to the legacy route.
   - Update `vm-api/CLAUDE.md` to drop the endpoint from the table.

**Why we didn't do this now.** Quickest unblock was the code fix (single-decorator removal). Switching to the Windmill path requires fixing the Windmill rot first and is reversible only by editing the Fireflies dashboard — wanted a working pipeline before doing that.

**Trade-offs at decision time.** Direct path = lower latency, fewer dependencies, no audit trail in Windmill, two parallel entry points to maintain. Windmill path = matches documented architecture, per-event observability, harder dependency on Windmill Cloud, single entry point.

## Restore Windmill `u/admin/telegram_chat_id` variable

**Status:** Open — failing every `health_check` since at least 2026-04-22.

The Windmill flow `f/automations/health_check` reads `u/admin/telegram_chat_id` to send Telegram alerts. The variable is missing (only `telegram_bot_token`, `vm_api_base_url`, `vm_api_secret` exist). Result: every health check errors with "Variable not found", so the VM could be down for days without paging.

Fix: re-create the variable in Windmill with the chat ID for the `Hitokiri_nic_bot` Telegram chat. Verify next `health_check` run is green.
