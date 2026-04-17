import httpx
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r'_*[]()~`>#+-=|{}.!'
    return "".join(f"\\{c}" if c in special else c for c in str(text))


async def notify_new_category(
    category: str,
    meeting_title: str,
    meeting_id: str,
    notebook_id: str,
) -> None:
    """Send a Telegram message when a new, unknown meeting category is detected."""
    message = (
        f"*New meeting category detected:* `{_escape_md(category)}`\n\n"
        f"Meeting: {_escape_md(meeting_title)}\n"
        f"Meeting ID: `{_escape_md(meeting_id)}`\n"
        f"Notebook ID: `{_escape_md(notebook_id)}`\n\n"
        f"A new NotebookLM notebook was created\\. Review and recategorize if needed\\."
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "MarkdownV2",
            },
            timeout=10.0,
        )
        response.raise_for_status()
