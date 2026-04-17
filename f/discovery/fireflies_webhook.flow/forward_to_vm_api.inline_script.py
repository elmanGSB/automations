import httpx
import wmill


def main(skip: bool, event: str, meeting_id: str, reason: str = "") -> dict:
    if skip:
        return {"status": "ignored", "reason": reason}

    vm_api_secret = wmill.get_variable("u/admin/vm_api_secret")
    vm_api_base_url = wmill.get_variable("u/admin/vm_api_base_url")

    # Split timeout: fail fast on connect (10s), allow up to 15 min for the pipeline read
    timeout = httpx.Timeout(connect=10.0, read=900.0, write=30.0, pool=10.0)

    with httpx.Client(timeout=timeout) as client:
        r = client.post(
            f"{vm_api_base_url}/api/pipeline/run",
            json={"meeting_id": meeting_id},
            headers={"Authorization": f"Bearer {vm_api_secret}"},
        )
        r.raise_for_status()
    return r.json()
