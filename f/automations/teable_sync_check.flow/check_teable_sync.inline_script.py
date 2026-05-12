import html
import httpx
import wmill


# Cap the number of Fireflies IDs we include in the Telegram body so a
# catastrophic drift (e.g. someone truncates Teable) doesn't blow past
# Telegram's 4096-char message limit.
MAX_IDS_IN_ALERT = 15


def _format_ids(ids: list[str]) -> str:
    if not ids:
        return "—"
    shown = ids[:MAX_IDS_IN_ALERT]
    extra = len(ids) - len(shown)
    body = ", ".join(f"<code>{html.escape(i)}</code>" for i in shown)
    if extra > 0:
        body += f" <i>(+{extra} more)</i>"
    return body


def main() -> dict:
    vm_api_base_url = wmill.get_variable("u/admin/vm_api_base_url")
    vm_api_secret = wmill.get_variable("u/admin/vm_api_secret")
    bot_token: str | None = wmill.get_variable("u/admin/telegram_bot_token")
    chat_id: str | None = wmill.get_variable("u/admin/telegram_chat_id")

    if not vm_api_base_url or not vm_api_secret:
        raise RuntimeError("VM API variables not configured")

    try:
        with httpx.Client(timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)) as client:
            r = client.get(
                f"{vm_api_base_url}/health/teable_sync",
                headers={"Authorization": f"Bearer {vm_api_secret}"},
            )
            r.raise_for_status()
            report = r.json()
    except Exception as e:
        report = {"status": "unreachable", "_error": str(e)[:200]}

    status = report.get("status")
    if status == "ok":
        return {"alerted": False, "report": report}

    if not bot_token or not chat_id:
        return {"alerted": False, "reason": "telegram_not_configured", "report": report}

    if status == "drift":
        missing = list(report.get("missing_in_teable", []))
        extra = list(report.get("extra_in_teable", []))
        message = (
            "<b>&#x26A0;&#xFE0F; Teable / Postgres drift</b>\n\n"
            f"Postgres: <code>{report.get('postgres_interviews', '?')}</code>\n"
            f"Teable: <code>{report.get('teable_interviews', '?')}</code>\n"
            f"Missing in Teable ({len(missing)}): {_format_ids(missing)}\n"
            f"Extra in Teable ({len(extra)}): {_format_ids(extra)}"
        )
    else:
        # unreachable / error / unknown
        err = html.escape(str(report.get("_error") or report.get("error") or "unknown")[:300])
        message = (
            f"<b>&#x1F534; Teable sync check failed</b>\n\n"
            f"Status: <code>{html.escape(str(status))}</code>\n"
            f"Detail: <code>{err}</code>"
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

    return {"alerted": True, "report": report}
