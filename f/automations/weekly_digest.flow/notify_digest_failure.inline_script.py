import html
import httpx
import wmill


def main(error: dict, flow_input: dict) -> dict:
    bot_token: str | None = wmill.get_variable("u/admin/telegram_bot_token")
    chat_id: str | None = wmill.get_variable("u/admin/telegram_chat_id")
    if not bot_token or not chat_id:
        return {"alerted": False, "reason": "telegram_not_configured"}

    error_msg = html.escape(str(error.get("error", error))[:500])
    message = f"<b>Weekly digest failed</b>\n\n<code>{error_msg}</code>"

    with httpx.Client(timeout=10.0) as client:
        r = client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
        )
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data.get('description')}")
    return {"alerted": True}
