import httpx
import wmill


def main() -> dict:
    vm_api_secret = wmill.get_variable("u/admin/vm_api_secret")
    vm_api_base_url = wmill.get_variable("u/admin/vm_api_base_url")

    if not vm_api_secret or not vm_api_base_url:
        raise RuntimeError("Windmill variables u/admin/vm_api_secret or u/admin/vm_api_base_url not set")

    timeout = httpx.Timeout(connect=10.0, read=900.0, write=30.0, pool=10.0)
    with httpx.Client(timeout=timeout) as client:
        r = client.post(
            f"{vm_api_base_url}/api/digest/run",
            headers={"Authorization": f"Bearer {vm_api_secret}"},
        )
        r.raise_for_status()
    return r.json()
