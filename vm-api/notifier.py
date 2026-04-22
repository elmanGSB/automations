import html
import os

import httpx
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r'_*[]()~`>#+-=|{}.!'
    return "".join(f"\\{c}" if c in special else c for c in str(text))


async def send_error(title: str, detail: str, **context: object) -> None:
    """Post an error alert to Telegram.

    Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID directly from os.environ
    so a misconfigured VM fails loudly (KeyError) instead of silently no-op'ing.
    HTTP errors are re-raised as RuntimeError without the original exception,
    so the bot token embedded in the URL never reaches logs.
    """
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    body = f"🔴 <b>{html.escape(title)}</b>\n\n{html.escape(detail)}"
    if context:
        ctx_lines = "\n".join(f"{k}: {v}" for k, v in context.items())
        body += f"\n\n<code>{html.escape(ctx_lines)}</code>"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": body, "parse_mode": "HTML"},
                timeout=5.0,
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Telegram API {e.response.status_code}") from None


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
