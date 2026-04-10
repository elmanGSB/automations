"""
Teable API client for dual-write from the discovery pipeline.
Writes records to Teable tables after Postgres inserts so data
appears in both the source-of-truth DB and the Teable UI.
"""

import json
import logging
import http.cookiejar
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

TEABLE_BASE_URL = "http://127.0.0.1:3200"
TEABLE_EMAIL = "elmanamador52@hotmail.com"
TEABLE_PASSWORD = "123eamGG!"

# Teable table IDs (from the "Interviews DB" base)
INTERVIEWS_TABLE = "tblINxPc5QnvO3vqogw"
INSIGHTS_TABLE = "tblx3633BHwOYpZVaPn"
CLUSTERS_TABLE = "tblXNM3aijcyxGVUpSU"


class TeableClient:
    """Synchronous Teable API client using cookie auth."""

    def __init__(self, base_url: str = TEABLE_BASE_URL):
        self.base_url = base_url
        self._cj = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cj)
        )
        self._authenticated = False

    def _request(self, method: str, path: str, data: dict | None = None) -> dict | None:
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        resp = self._opener.open(req)
        raw = resp.read().decode()
        return json.loads(raw) if raw else None

    def login(self) -> None:
        if self._authenticated:
            return
        self._request("POST", "/api/auth/signin", {
            "email": TEABLE_EMAIL,
            "password": TEABLE_PASSWORD,
        })
        self._authenticated = True

    def create_records(self, table_id: str, records: list[dict]) -> int:
        """Insert records into a Teable table. Returns count created."""
        self.login()
        created = 0
        # Teable API requires {"records": [{"fields": {...}}, ...]}
        # Max batch size ~100, we use 10 for safety
        for i in range(0, len(records), 10):
            batch = [{"fields": r} for r in records[i:i + 10]]
            try:
                result = self._request("POST", f"/api/table/{table_id}/record", {
                    "records": batch,
                })
                created += len(result.get("records", []))
            except urllib.error.HTTPError as e:
                logger.warning("Teable batch insert failed: %s", e)
                # Fall back to one-at-a-time
                for rec in batch:
                    try:
                        self._request("POST", f"/api/table/{table_id}/record", {
                            "records": [rec],
                        })
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
