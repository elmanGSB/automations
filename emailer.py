import httpx
import logging
from analyzer import AnalysisResult

AGENTMAIL_API_KEY = "am_us_c3b97b3755fd41dcb848e2eef208f653bae75fb42ccb95aa5aa9762c02bd0e82"
AGENTMAIL_INBOX = "customer_discovery@agentmail.to"
AGENTMAIL_BASE_URL = "https://api.agentmail.to/v0"
RECIPIENTS = ["elman@stanford.edu", "kklara@stanford.edu"]

logger = logging.getLogger(__name__)


async def send_meeting_report(
    meeting_title: str,
    category: str,
    analysis: AnalysisResult,
) -> None:
    """Email both analysis reports to all recipients."""
    subject = f"[{category.replace('-', ' ').title()}] Meeting Report: {meeting_title}"

    text = (
        f"Meeting: {meeting_title}\n"
        f"Category: {category}\n\n"
        f"{'='*60}\n"
        f"INTERVIEW INSIGHTS & PATTERNS\n"
        f"{'='*60}\n\n"
        f"{analysis.patterns}\n\n"
        f"{'='*60}\n"
        f"WHAT'S NEW IN THIS INTERVIEW\n"
        f"{'='*60}\n\n"
        f"{analysis.novel}\n"
    )

    html = f"""
<html><body style="font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #1a56db;">{meeting_title}</h2>
  <p style="color: #666;">Category: <strong>{category.replace('-', ' ').title()}</strong></p>

  <hr style="border: 1px solid #e5e7eb; margin: 24px 0;">

  <h3 style="color: #111827;">Interview Insights &amp; Patterns</h3>
  <div style="white-space: pre-wrap; line-height: 1.6; color: #374151;">{analysis.patterns}</div>

  <hr style="border: 1px solid #e5e7eb; margin: 24px 0;">

  <h3 style="color: #111827;">What's New in This Interview</h3>
  <div style="white-space: pre-wrap; line-height: 1.6; color: #374151;">{analysis.novel}</div>
</body></html>
"""

    url = f"{AGENTMAIL_BASE_URL}/inboxes/{AGENTMAIL_INBOX}/messages/send"
    headers = {
        "Authorization": f"Bearer {AGENTMAIL_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        for recipient in RECIPIENTS:
            payload = {
                "to": [{"email": recipient}],
                "subject": subject,
                "text": text,
                "html": html,
            }
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            logger.info("Sent meeting report to %s", recipient)
