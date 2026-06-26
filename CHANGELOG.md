# Changelog

All notable changes to this project will be documented in this file.

## [0.0.0.1] - 2026-06-26

### Added

- **Opus 4.8 via Max proxy** — `claude-opus-4-8` and `claude-opus` are now routable through LiteLLM using the existing Max-subscription proxy. Calls are $0 against the Max plan, no API key required. Callers that hardcode `claude-opus-4-8` (e.g. n8n Anthropic node) route automatically; callers that use the short alias `claude-opus` do too.

