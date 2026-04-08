"""Bidirectional Telegram bot: founders can query NotebookLM notebooks."""
import asyncio
import logging
import httpx
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from state import get_all_notebooks
from analyzer import query_notebook

logger = logging.getLogger(__name__)

# Authorized chat IDs — only these users can query notebooks
AUTHORIZED_CHAT_IDS: set[str] = {str(TELEGRAM_CHAT_ID)} if TELEGRAM_CHAT_ID else set()

BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


async def _send(client: httpx.AsyncClient, chat_id: int | str, text: str) -> None:
    await client.post(f"{BASE}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }, timeout=15)


def _pick_notebook(text: str, notebooks: dict[str, str]) -> tuple[str, str] | None:
    """Return (category, notebook_id) by matching keywords in the message, or first if only one."""
    text_lower = text.lower()
    for category, notebook_id in notebooks.items():
        if any(word in text_lower for word in category.replace("-", " ").split()):
            return category, notebook_id
    # Default to first available notebook
    if notebooks:
        category, notebook_id = next(iter(notebooks.items()))
        return category, notebook_id
    return None


def _handle_message(text: str, notebooks: dict[str, str]) -> str:
    text = text.strip()

    if text.startswith("/notebooks") or text.startswith("/list"):
        if not notebooks:
            return "No notebooks found yet."
        lines = [f"*Available notebooks:*"]
        for cat, nb_id in notebooks.items():
            label = cat.replace("-", " ").title()
            lines.append(f"• {label} — `{nb_id[:8]}…`")
        lines.append("\nSend a question to query a notebook. Prefix with a category name to target it.")
        return "\n".join(lines)

    if text.startswith("/help") or text.startswith("/start"):
        return (
            "*Interview Router Bot*\n\n"
            "Ask any question and I'll query your NotebookLM notebooks.\n\n"
            "Commands:\n"
            "• `/notebooks` — list available notebooks\n"
            "• `/help` — show this message\n\n"
            "Examples:\n"
            "• _What are the top pain points from customer discovery?_\n"
            "• _customer-discovery: What workarounds do users have?_"
        )

    # Strip command prefix if present (e.g. /ask What are...)
    if text.startswith("/ask "):
        text = text[5:]
    elif text.startswith("/query "):
        text = text[7:]

    if not notebooks:
        return "No notebooks available yet — process a meeting first."

    pick = _pick_notebook(text, notebooks)
    if pick is None:
        return "No notebooks found."

    category, notebook_id = pick
    label = category.replace("-", " ").title()

    try:
        answer = query_notebook(notebook_id, text, timeout=120)
        return f"*{label}*\n\n{answer}"
    except Exception as exc:
        logger.error("Query failed: %s", exc)
        return f"Query failed: {exc}"


async def run_bot() -> None:
    """Long-poll loop."""
    offset = 0
    logger.info("Telegram bot started (authorized: %s)", AUTHORIZED_CHAT_IDS)

    async with httpx.AsyncClient() as client:
        while True:
            try:
                resp = await client.get(f"{BASE}/getUpdates", params={
                    "offset": offset,
                    "timeout": 30,
                    "allowed_updates": ["message"],
                }, timeout=40)
                resp.raise_for_status()
                updates = resp.json().get("result", [])
            except Exception:
                logger.exception("getUpdates failed, retrying in 5s")
                await asyncio.sleep(5)
                continue

            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "").strip()

                if not text or not chat_id:
                    continue

                if chat_id not in AUTHORIZED_CHAT_IDS:
                    logger.warning("Ignoring unauthorized chat_id=%s", chat_id)
                    continue

                logger.info("Message from %s: %s", chat_id, text[:80])
                notebooks = get_all_notebooks()

                # Send "thinking..." indicator for queries
                is_query = not any(
                    text.startswith(cmd)
                    for cmd in ["/notebooks", "/list", "/help", "/start"]
                )
                if is_query:
                    await _send(client, chat_id, "_Querying notebook, please wait…_")

                reply = _handle_message(text, notebooks)
                await _send(client, chat_id, reply)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_bot())
