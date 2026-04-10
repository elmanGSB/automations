# Interview Router

Automated pipeline that receives Fireflies webhooks, classifies meetings, generates role-labeled transcripts, and routes them to NotebookLM notebooks for AI analysis. Sends novel insight reports by email after each meeting.

## Architecture

```
Fireflies webhook
      ↓
POST /webhook/fireflies  (main.py)
      ↓
classify_speakers()      (speaker_roles.py)   → who is internal vs external
      ↓
format transcripts       (transcript_formatter.py)
  ├── labeled_transcript   [BROCCOLI TEAM] / [INTERVIEWEE] tags
  └── external_transcript  [CONTEXT/QUESTION] Elman: ... / [INTERVIEWEE] ...
      ↓
classify_meeting()       (classifier.py)      → meeting category
      ↓
┌─────────────────────────────────────────────┐
│ if customer-discovery                        │
│   process_discovery_meeting()               │ → Postgres + Teable
│   (discovery_extractor.py)                 │
└─────────────────────────────────────────────┘
      ↓
generate_transcript_pdf()  (pdf_generator.py) → role-labeled PDF
      ↓
NotebookLM notebook        (notebooklm.py)    → add PDF as source
      ↓
analyze_novel()            (analyzer.py)      → novel insights vs prior meetings
      ↓
send_novel_report()        (emailer.py)       → email to founders
      ↓
retain in Hindsight        (hindsight.py)     → long-term memory
```

## Speaker Role System

Every transcript is labeled before any AI step runs:

| Label | Who | Used for |
|-------|-----|----------|
| `[BROCCOLI TEAM] Name:` | Elman, Klara, or anyone matching `INTERNAL_TEAM_NAMES` | Context only — not extracted as insights |
| `[INTERVIEWEE] Name:` | External party | Primary data source for all AI analysis |
| `[CONTEXT/QUESTION] Name: ...` | Internal team question (in extraction format) | Frames the interviewee's next response |

**Two transcript variants are produced per meeting:**

- `labeled_transcript` — full conversation with `[BROCCOLI TEAM]`/`[INTERVIEWEE]` tags. Used by the classifier and uploaded to NotebookLM as the PDF.
- `external_transcript` — collapses internal turns into `[CONTEXT/QUESTION]` blocks. Used by the discovery extractor so insights come exclusively from the interviewee.

Internal team members are matched by substring (case-insensitive) against `INTERNAL_TEAM_NAMES` in `config.py`. Add names there to expand the team.

## Meeting Categories

The classifier assigns each meeting to a category. Each category gets its own NotebookLM notebook.

**Business meetings:**
| Slug | Description |
|------|-------------|
| `customer-discovery` | Customer interviews, sales calls, distributor/retailer/supplier conversations |
| `investor-calls` | VCs, angels, fundraising |
| `team-syncs` | Internal standups, retrospectives |
| `competitors` | Competitive research calls |
| `advisors` | Advisor and mentor meetings |

**Stanford GSB classes (Q3 2026):**
| Slug | Course |
|------|--------|
| `class-mge` | Managing Growing Enterprises |
| `class-sales` | Building Sales Organizations |
| `class-leadership` | The Art of Leading in Challenging Times |
| `class-taxes` | Taxes and Business Strategy |
| `class-fsa` | Financial Statement Analysis |

Unknown meeting types get a generated slug (e.g. `conference-panel`).

## Deduplication

Processed meeting IDs are stored in `state.json`. The pipeline skips any `meeting_id` it has already seen — so if multiple team members are on the same Fireflies call, only one email is sent.

## Setup

**Environment variables** (`.env` file or system env):

```bash
FIREFLIES_API_KEY=...
FIREFLIES_WEBHOOK_SECRET=...   # optional — skips signature check if empty
TELEGRAM_BOT_TOKEN=...          # optional — for Telegram notifications
TELEGRAM_CHAT_ID=...
```

**Install dependencies:**

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

**Run locally:**

```bash
venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001
```

**Run tests:**

```bash
venv/bin/pytest tests/ -v
```

## Service (systemd)

The service runs on `paperclip-vm` at port 8001.

```bash
sudo systemctl status interview-router
sudo systemctl restart interview-router
journalctl -u interview-router -f
```

## Manual Trigger

Re-process or force-process a specific meeting:

```bash
curl -X POST http://localhost:8001/webhook/fireflies \
  -H 'Content-Type: application/json' \
  -d '{"event":"meeting.transcribed","meeting_id":"<MEETING_ID>"}'
```

To re-process an already-processed meeting, remove its ID from `state.json` first.

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, webhook handler, signature verification |
| `pipeline.py` | Orchestrates the full meeting processing flow |
| `config.py` | API keys, known categories, internal team names |
| `speaker_roles.py` | Classifies speakers as internal or external |
| `transcript_formatter.py` | Produces labeled and external-only transcript formats |
| `classifier.py` | Sends transcript to Claude proxy, returns meeting category |
| `discovery_extractor.py` | Extracts structured insights from customer-discovery calls |
| `pdf_generator.py` | Generates role-labeled PDF for NotebookLM upload |
| `notebooklm.py` | Creates notebooks and uploads PDF sources |
| `analyzer.py` | Queries NotebookLM for novel insights via the AI prompt |
| `emailer.py` | Sends insight report emails via AgentMail |
| `hindsight.py` | Retains meeting context in Hindsight long-term memory |
| `state.py` | Reads/writes `state.json` — processed meeting IDs + notebook IDs |
| `weekly_report.py` | Runs the patterns analysis prompt across all notebooks |
| `telegram_bot.py` | Sends Telegram alerts for new meeting categories |
