import httpx
import wmill


def main(skip: bool, event: str, meeting_id: str, reason: str = "") -> dict:
    if skip:
        return {"status": "ignored", "reason": reason}

    vm_api_secret = wmill.get_variable("u/admin/vm_api_secret")
    vm_api_base_url = wmill.get_variable("u/admin/vm_api_base_url")
    cf_access_id = wmill.get_variable("u/admin/cf_access_client_id")
    cf_access_secret = wmill.get_variable("u/admin/cf_access_client_secret")

    if not vm_api_secret or not vm_api_base_url:
        raise RuntimeError("Windmill variables u/admin/vm_api_secret or u/admin/vm_api_base_url not set")
    if not cf_access_id or not cf_access_secret:
        raise RuntimeError("Cloudflare Access variables u/admin/cf_access_client_id or u/admin/cf_access_client_secret not set")

    # Split timeout: fail fast on connect (10s), allow up to 15 min for the pipeline read
    timeout = httpx.Timeout(connect=10.0, read=900.0, write=30.0, pool=10.0)

    with httpx.Client(timeout=timeout) as client:
        r = client.post(
            f"{vm_api_base_url}/api/pipeline/run",
            json={"meeting_id": meeting_id},
            headers={
                "Authorization": f"Bearer {vm_api_secret}",
                "CF-Access-Client-Id": cf_access_id,
                "CF-Access-Client-Secret": cf_access_secret,
            },
        )
        r.raise_for_status()
    return r.json()
