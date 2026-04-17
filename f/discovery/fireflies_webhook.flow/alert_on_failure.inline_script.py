import html
import httpx
import wmill

# Fatal steps only — non-fatal steps (email, hindsight, notify) are excluded
_FATAL_STEPS = {"fetch", "classify_meeting", "notebooklm_notebook", "notebooklm_upload", "nlm_analysis"}


def main(pipeline_result: dict, meeting_id: str) -> dict:
    if pipeline_result.get("status") in ("skipped", "ignored"):
        return {"alerted": False, "reason": "skipped"}

    # Check top-level status first — catches early failures where steps is empty
    top_level_error = pipeline_result.get("status") == "error"

    # Check per-step errors (only fatal steps)
    steps = pipeline_result.get("steps") or {}
    errored_steps = [
        step for step, info in steps.items()
        if step in _FATAL_STEPS and isinstance(info, dict) and info.get("status") == "error"
    ]

    if not top_level_error and not errored_steps:
        return {"alerted": False, "reason": "all_ok"}

    bot_token: str | None = wmill.get_variable("u/admin/telegram_bot_token")
    chat_id: str | None = wmill.get_variable("u/admin/telegram_chat_id")
    if not bot_token or not chat_id:
        return {"alerted": False, "reason": "telegram_not_configured"}

    title = html.escape(pipeline_result.get("title") or meeting_id or "Unknown")
    category = html.escape(pipeline_result.get("category") or "unknown")
    steps_str = html.escape(", ".join(errored_steps) if errored_steps else "unknown (top-level error)")

    message = (
        f"<b>&#x26A0; Pipeline error</b>\n\n"
        f"Meeting: {title}\n"
        f"Category: {category}\n"
        f"Failed steps: <code>{steps_str}</code>"
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

    return {"alerted": True, "errored_steps": errored_steps, "top_level_error": top_level_error}
