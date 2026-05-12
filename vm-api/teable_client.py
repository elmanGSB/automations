"""
Teable API client for dual-write from the discovery pipeline.

Writes records to Teable tables after Postgres inserts so data appears in
both the source-of-truth DB and the Teable UI.

Auth: Personal Access Token (Bearer). Set TEABLE_TOKEN in env. The token is
generated once in the Teable UI (Settings → Personal Access Tokens) and
must have record|read + record|create scopes on the Interviews DB base.
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

TEABLE_BASE_URL = os.environ.get("TEABLE_BASE_URL", "http://127.0.0.1:3200")

# Teable table IDs (from the "Interviews DB" base, bseEuelyInFqZdXNY0D)
INTERVIEWS_TABLE = "tblINxPc5QnvO3vqogw"
INSIGHTS_TABLE = "tblx3633BHwOYpZVaPn"
CLUSTERS_TABLE = "tblXNM3aijcyxGVUpSU"


class TeableAuthError(RuntimeError):
    """Raised when TEABLE_TOKEN is missing or rejected by Teable."""


class TeableClient:
    """Synchronous Teable API client using Personal Access Token (Bearer)."""

    def __init__(self, base_url: str = TEABLE_BASE_URL, token: str | None = None):
        self.base_url = base_url
        self._token = token if token is not None else os.environ.get("TEABLE_TOKEN", "")
        if not self._token:
            raise TeableAuthError(
                "TEABLE_TOKEN is not set. Generate a Personal Access Token in the "
                "Teable UI (Settings → Personal Access Tokens) and add it to the VM .env."
            )

    def _request(self, method: str, path: str, data: dict | None = None) -> dict | None:
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self._token}")
        try:
            resp = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="replace")
            if e.code in (401, 403):
                raise TeableAuthError(
                    f"Teable rejected the PAT ({e.code}): {err_body}"
                ) from e
            # Re-raise with body so callers see the actual error
            raise urllib.error.HTTPError(
                e.url, e.code, f"{e.reason}: {err_body}", e.headers, None
            ) from e
        raw = resp.read().decode()
        return json.loads(raw) if raw else None

    def create_records(self, table_id: str, records: list[dict]) -> int:
        """Insert records into a Teable table. Returns count created.

        Uses fieldKeyType=name so callers can pass user-facing field names
        (e.g. "Participant") instead of internal field IDs.
        """
        created = 0
        path = f"/api/table/{table_id}/record?{urllib.parse.urlencode({'fieldKeyType': 'name'})}"
        # Teable accepts batches up to ~100; we use 10 for safety.
        for i in range(0, len(records), 10):
            batch = [{"fields": r} for r in records[i:i + 10]]
            try:
                result = self._request("POST", path, {"records": batch})
                created += len(result.get("records", []))
            except urllib.error.HTTPError as e:
                logger.warning("Teable batch insert failed: %s", e)
                # Fall back to one-at-a-time so a single bad record doesn't lose the batch.
                for rec in batch:
                    try:
                        self._request("POST", path, {"records": [rec]})
                        created += 1
                    except urllib.error.HTTPError as e2:
                        logger.error("Teable single insert failed: %s", e2)
        return created

    def write_interview(self, *, participant_name: str, date: str,
                        participant_role: str = "", company_name: str = "",
                        interviewee_type: str = "", product_categories: list[str] | None = None,
                        behavioral_segment: str = "", demographics: str = "",
                        summary: str = "", fireflies_meeting_id: str = "") -> int:
        return self.create_records(INTERVIEWS_TABLE, [{
            "Participant": participant_name,
            "Date": date,
            "Role": participant_role,
            "Company": company_name,
            "Type": interviewee_type,
            "Products": ", ".join(product_categories or []),
            "Segment": behavioral_segment,
            "Demographics": demographics,
            "Summary": summary,
            "Fireflies ID": fireflies_meeting_id,
        }])

    def write_insights(self, insights: list[dict]) -> int:
        """Write multiple insights. Each dict has: interview, type, category, content, severity, sentiment, quote."""
        records = [{
            "Interview": ins.get("interview", ""),
            "Type": ins.get("type", ""),
            "Category": ins.get("category", ""),
            "Content": ins.get("content", ""),
            "Severity": ins.get("severity", ""),
            "Sentiment": ins.get("sentiment", ""),
            "Quote": ins.get("quote", ""),
        } for ins in insights]
        return self.create_records(INSIGHTS_TABLE, records)

    def write_clusters(self, clusters: list[dict]) -> int:
        """Write multiple clusters. Each dict has: user_type, need, insight, quote, category."""
        records = [{
            "User Type": cl.get("user_type", ""),
            "Need": cl.get("need", ""),
            "Insight": cl.get("insight", ""),
            "Quote": cl.get("quote", ""),
            "Category": cl.get("category", ""),
        } for cl in clusters]
        return self.create_records(CLUSTERS_TABLE, records)
