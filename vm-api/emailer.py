import httpx
import logging
import markdown as md

AGENTMAIL_API_KEY = "am_us_c3b97b3755fd41dcb848e2eef208f653bae75fb42ccb95aa5aa9762c02bd0e82"
AGENTMAIL_INBOX = "customer_discovery@agentmail.to"
AGENTMAIL_BASE_URL = "https://api.agentmail.to/v0"
RECIPIENTS = ["elman@stanford.edu", "kklara@stanford.edu"]

logger = logging.getLogger(__name__)

_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f9fafb; margin: 0; padding: 24px; }
.card { background: #ffffff; border-radius: 12px; max-width: 700px; margin: 0 auto; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
.header { background: #1a56db; padding: 28px 32px; }
.header h1 { color: #ffffff; margin: 0 0 6px; font-size: 22px; font-weight: 700; }
.header p { color: #bfdbfe; margin: 0; font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; }
.section { padding: 28px 32px; border-bottom: 1px solid #f3f4f6; }
.section:last-child { border-bottom: none; }
.section-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #6b7280; margin: 0 0 16px; }
.section h3 { color: #111827; font-size: 16px; margin: 20px 0 8px; }
.section h3:first-child { margin-top: 0; }
.section p { color: #374151; line-height: 1.65; margin: 0 0 12px; font-size: 14px; }
.section ul, .section ol { color: #374151; line-height: 1.65; margin: 0 0 12px; padding-left: 20px; font-size: 14px; }
.section li { margin-bottom: 6px; }
.section strong { color: #111827; }
.section em { color: #6b7280; font-style: italic; }
blockquote { border-left: 3px solid #1a56db; margin: 12px 0; padding: 8px 16px; background: #eff6ff; border-radius: 0 6px 6px 0; color: #1e40af; font-style: italic; font-size: 14px; }
.novel-badge { display: inline-block; background: #fef3c7; color: #92400e; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px; }
.weekly-badge { display: inline-block; background: #d1fae5; color: #065f46; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px; }
"""


def _to_html(text: str) -> str:
    """Convert markdown to HTML."""
    return md.markdown(text, extensions=["nl2br", "sane_lists"])


async def _send(subject: str, html: str, text: str) -> None:
    url = f"{AGENTMAIL_BASE_URL}/inboxes/{AGENTMAIL_INBOX}/messages/send"
    headers = {
        "Authorization": f"Bearer {AGENTMAIL_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        for recipient in RECIPIENTS:
            resp = await client.post(url, headers=headers, json={
                "to": [recipient],
                "subject": subject,
                "text": text,
                "html": html,
            })
            resp.raise_for_status()
            logger.info("Sent email to %s", recipient)


async def send_novel_report(
    meeting_title: str,
    category: str,
    novel: str,
) -> None:
    """Email novel insights from a single meeting (Prompt 2)."""
    subject = f"[{category.replace('-', ' ').title()}] New Interview: {meeting_title}"
    novel_html = _to_html(novel)

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>{_CSS}</style></head>
<body>
<div class="card">
  <div class="header">
    <h1>{meeting_title}</h1>
    <p>Category: {category.replace('-', ' ').title()}</p>
  </div>

  <div class="section">
    <div class="novel-badge">&#x2728; What's New</div>
    <div class="section-label">Novel Insights from This Interview</div>
    {novel_html}
  </div>
</div>
</body>
</html>"""

    text = (
        f"Meeting: {meeting_title}\nCategory: {category}\n\n"
        f"--- NOVEL INSIGHTS FROM THIS INTERVIEW ---\n\n{novel}"
    )

    await _send(subject, html, text)


async def send_patterns_report(category: str, patterns: str) -> None:
    """Email weekly aggregate patterns report (Prompt 1)."""
    subject = f"[Weekly] Interview Patterns — {category.replace('-', ' ').title()}"
    patterns_html = _to_html(patterns)

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>{_CSS}</style></head>
<body>
<div class="card">
  <div class="header">
    <h1>Weekly Patterns Report</h1>
    <p>Category: {category.replace('-', ' ').title()}</p>
  </div>

  <div class="section">
    <div class="weekly-badge">&#x1f4ca; Weekly Summary</div>
    <div class="section-label">Interview Insights &amp; Patterns</div>
    {patterns_html}
  </div>
</div>
</body>
</html>"""

    text = (
        f"Category: {category}\n\n"
        f"--- WEEKLY INTERVIEW INSIGHTS & PATTERNS ---\n\n{patterns}"
    )

    await _send(subject, html, text)
