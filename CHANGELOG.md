# Changelog

All notable changes to this project will be documented in this file.

## [0.0.1.0] - 2026-06-29

### Changed

- **classify_meeting now runs on Gemini 3.1 Pro via LiteLLM** — previously it called the Max-subscription Claude proxy directly, so it depended on the Mac's OAuth token being synced fresh to the VM. When that token went stale (Mac asleep / not on Claude Code), classification 401'd and the pipeline failed, sometimes for days. It now posts an OpenAI-shaped chat completion to the LiteLLM gateway using the `gemini-3-1-pro` alias (`gemini/gemini-3.1-pro-preview`), authenticated with a static API key. LiteLLM's `default_fallbacks` drops to `gemini-3-1-flash-lite` if Pro errors. Claude stays the engine for discovery extraction and the Attio triage resolver.
- **`CLASSIFY_MODEL` env var** (default `gemini-3-1-pro`) selects the classifier model; must match a `model_name` in `infra/litellm/config.yaml`.
- **Deploy wires `LITELLM_API_KEY`** into the vm-api `.env` from the `LITELLM_MASTER_KEY` CI secret (fail-loud if unset), so vm-api can authenticate to the gateway. Verified live: gateway returns 200 with the key, and `gemini-3.1-pro-preview` is reachable with the VM's `GEMINI_API_KEY`.

### Added

- `gemini-3-1-pro` model alias in the LiteLLM config.
- Mocked classifier unit tests (request shape, JSON-fence parsing, new-category detection, unparseable-reply handling).

## [0.0.0.2] - 2026-06-26

### Fixed

- **OAuth credential self-heal hardened** — the VM's credential refresh now uses `mkstemp` to create the temporary credentials file at 0o600 *before* any data is written, eliminating a window where the file was briefly world-readable. Also eliminates a cross-process clobber race (fixed `.tmp` path replaced with unique temp file per call).
- **Peer-thread short-circuit** — if two pipeline threads hit a 401 simultaneously, the second thread now re-reads credentials after acquiring the lock. If the first thread already refreshed, the second returns immediately instead of making a redundant OAuth call that could consume a rotating refresh token.
- **Secret Manager output validated** — the gcloud fallback now parses the output as JSON before writing it to disk. Prevents a corrupt-credentials loop if gcloud emits banners or partial output on stdout.
- **OAuth response read capped** — `resp.read()` is now bounded to 64 KB, preventing memory exhaustion from a hostile or misconfigured OAuth endpoint response.

## [0.0.0.1] - 2026-06-26

### Added

- **Opus 4.8 via Max proxy** — `claude-opus-4-8` and `claude-opus` are now routable through LiteLLM using the existing Max-subscription proxy. Calls are $0 against the Max plan, no API key required. Callers that hardcode `claude-opus-4-8` (e.g. n8n Anthropic node) route automatically; callers that use the short alias `claude-opus` do too.

