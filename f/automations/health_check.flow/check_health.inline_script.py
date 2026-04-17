import html
import httpx
import wmill


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
                f"{vm_api_base_url}/health/full",
                headers={"Authorization": f"Bearer {vm_api_secret}"},
            )
            r.raise_for_status()
            health = r.json()
    except Exception as e:
        health = {"status": "unreachable", "checks": {}, "_error": str(e)[:200]}

    if health.get("status") == "ok":
        return {"alerted": False, "health": health}

    if not bot_token or not chat_id:
        return {"alerted": False, "reason": "telegram_not_configured", "health": health}

    # Alert: include only failed check names, not their raw error strings
    failed_checks = [name for name, val in health.get("checks", {}).items() if val != "ok"]
    detail = html.escape(", ".join(failed_checks) if failed_checks else "unreachable")
    message = (
        f"<b>&#x1F534; VM health degraded</b>\n\n"
        f"Status: <code>{html.escape(health.get('status', 'unknown'))}</code>\n"
        f"Failed: <code>{detail}</code>"
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

    health_safe = {k: v for k, v in health.items() if k != "_error"}
    return {"alerted": True, "health": health_safe, "failed_checks": failed_checks}
