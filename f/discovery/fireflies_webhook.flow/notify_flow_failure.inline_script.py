import html
import httpx
import wmill


def main(error: dict, flow_input: dict) -> dict:
    bot_token: str | None = wmill.get_variable("u/admin/telegram_bot_token")
    chat_id: str | None = wmill.get_variable("u/admin/telegram_chat_id")
    if not bot_token or not chat_id:
        return {"alerted": False, "reason": "telegram_not_configured"}

    meeting_id = html.escape(str(flow_input.get("meetingId") or flow_input.get("meeting_id") or "unknown"))
    error_msg = html.escape(str(error.get("error", error))[:300])
    message = (
        f"<b>&#x1F534; Pipeline flow failed</b>\n\n"
        f"Meeting ID: <code>{meeting_id}</code>\n"
        f"Error: <code>{error_msg}</code>"
    )

    with httpx.Client(timeout=10.0) as client:
        r = client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data.get('description')}")

    return {"alerted": True}
