import httpx
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


async def notify_new_category(
    category: str,
    meeting_title: str,
    meeting_id: str,
    notebook_id: str,
) -> None:
    """Send a Telegram message when a new, unknown meeting category is detected."""
    message = (
        f"*New meeting category detected:* `{category}`\n\n"
        f"Meeting: {meeting_title}\n"
        f"Meeting ID: `{meeting_id}`\n"
        f"Notebook ID: `{notebook_id}`\n\n"
        f"A new NotebookLM notebook was created. Review and recategorize if needed."
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
            },
            timeout=10.0,
        )
        response.raise_for_status()
