import importlib

import pytest
import asyncpg
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date


def test_database_url_reads_from_env(monkeypatch):
    """DATABASE_URL in discovery_extractor must come from env, not be hardcoded."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/testdb")
    import discovery_extractor
    importlib.reload(discovery_extractor)
    assert discovery_extractor.DATABASE_URL == "postgresql://user:pass@host:5432/testdb"


def test_database_url_has_default(monkeypatch):
    """DATABASE_URL falls back to local default when env var not set."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import discovery_extractor
    importlib.reload(discovery_extractor)
    assert "5432" in discovery_extractor.DATABASE_URL


from discovery_extractor import store_extraction as store_extraction_fn


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def make_mock_conn():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)   # no duplicate by default
    conn.fetchval = AsyncMock(return_value=42)     # INSERT RETURNING id
    conn.execute = AsyncMock()
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=False)
    conn.transaction.return_value = txn
    return conn


def make_mock_pool(conn=None):
    if conn is None:
        conn = make_mock_conn()
    pool = MagicMock(spec=asyncpg.Pool)
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = acquire
    return pool, conn


# ---------------------------------------------------------------------------
# Transaction tests (new — should FAIL before the fix)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_extraction_uses_transaction():
    """store_extraction must wrap all DB writes in a single transaction."""
    pool, conn = make_mock_pool()
    extraction = {
        "interviewee_type": "distributor",
        "insights": [],
        "clusters": [],
        "summary": "s",
        "participant_role": None,
        "company_name": None,
        "product_categories": [],
        "behavioral_segment": None,
        "demographics": None,
    }

    with patch("discovery_extractor.TeableClient"):
        await store_extraction_fn(
            pool=pool,
            extraction=extraction,
            participant_name="John",
            interview_date=date(2026, 4, 16),
            transcript_text="text",
        )

    pool.acquire.assert_called_once()
    conn.transaction.assert_called_once()
    conn.transaction.return_value.__aenter__.assert_awaited_once()


@pytest.mark.asyncio
async def test_store_extraction_partial_failure_propagates():
    """Exception during child insert must propagate so asyncpg can roll back."""
    conn = make_mock_conn()
    conn.execute = AsyncMock(side_effect=RuntimeError("constraint violation"))
    pool, _ = make_mock_pool(conn)

    extraction = {
        "interviewee_type": "distributor",
        "insights": [{"type": "problem", "content": "bad insert"}],
        "clusters": [],
        "summary": "",
        "participant_role": None,
        "company_name": None,
        "product_categories": [],
        "behavioral_segment": None,
        "demographics": None,
    }

    with patch("discovery_extractor.TeableClient"):
        with pytest.raises(RuntimeError, match="constraint violation"):
            await store_extraction_fn(
                pool=pool,
                extraction=extraction,
                participant_name="Test",
                interview_date=date(2026, 4, 16),
                transcript_text="text",
            )

    # transaction.__aexit__ receives the exception → asyncpg rolls back on real DB
    conn.transaction.return_value.__aexit__.assert_awaited()


# ---------------------------------------------------------------------------
# Pool-threading tests (updated from Task 4 — assert on conn, not pool)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_extraction_uses_injected_pool():
    """store_extraction must use the passed pool (via acquire), not create its own."""
    pool, conn = make_mock_pool()
    extraction = {
        "interviewee_type": "distributor",
        "insights": [],
        "clusters": [],
        "summary": "test",
        "participant_role": "Owner",
        "company_name": "Acme",
        "product_categories": ["frozen"],
        "behavioral_segment": "extreme_user",
        "demographics": "10 years",
    }

    with patch("discovery_extractor.asyncpg") as mock_asyncpg, \
         patch("discovery_extractor.TeableClient"):
        result = await store_extraction_fn(
            pool=pool,
            extraction=extraction,
            participant_name="John",
            interview_date=date(2026, 4, 16),
            transcript_text="Hello world",
        )

    mock_asyncpg.create_pool.assert_not_called()
    conn.fetchval.assert_awaited_once()   # INSERT ... RETURNING id used the connection
    assert result["interview_id"] == 42


@pytest.mark.asyncio
async def test_process_discovery_meeting_threads_pool():
    """process_discovery_meeting must accept and thread pool through."""
    from discovery_extractor import process_discovery_meeting

    pool, _ = make_mock_pool()

    fake_extraction = {
        "interviewee_type": "distributor",
        "behavioral_segment": "extreme_user",
        "insights": [],
        "clusters": [],
        "summary": "s",
        "participant_role": None,
        "company_name": None,
        "product_categories": [],
        "demographics": None,
    }

    with patch("discovery_extractor.extract_discovery_insights", AsyncMock(return_value=fake_extraction)), \
         patch("discovery_extractor.store_extraction", AsyncMock(return_value={"interview_id": 1})) as mock_store, \
         patch("discovery_extractor.TeableClient"):
        await process_discovery_meeting(
            pool=pool,
            transcript_text="text",
            participant_name="Jane",
            meeting_date="2026-04-16",
        )

    call = mock_store.call_args
    passed_pool = call.kwargs.get("pool") or (call.args[0] if call.args else None)
    assert passed_pool is pool


@pytest.mark.asyncio
async def test_teable_timeout_is_non_fatal():
    """Teable timeout must not raise — logged as warning, pipeline succeeds."""
    import asyncio as _asyncio
    pool, _ = make_mock_pool()
    extraction = {
        "interviewee_type": "distributor",
        "insights": [],
        "clusters": [],
        "summary": "",
        "participant_role": None,
        "company_name": None,
        "product_categories": [],
        "behavioral_segment": None,
        "demographics": None,
    }

    with patch("discovery_extractor.asyncio.wait_for", side_effect=_asyncio.TimeoutError), \
         patch("discovery_extractor.TeableClient"):
        result = await store_extraction_fn(
            pool=pool,
            extraction=extraction,
            participant_name="Test",
            interview_date=date(2026, 4, 16),
            transcript_text="text",
        )

    # Pipeline must succeed despite Teable timeout
    assert result["interview_id"] == 42


@pytest.mark.asyncio
async def test_teable_auth_error_pages_telegram_and_continues():
    """TeableAuthError must trigger notifier.send_error and not propagate.

    Regression: an earlier revision referenced TeableAuthError/send_error
    without importing them, which turned the auth-failure branch into a
    silent NameError instead of the intended Telegram alert.
    """
    from discovery_extractor import TeableAuthError

    pool, _ = make_mock_pool()
    extraction = {
        "interviewee_type": "distributor",
        "insights": [],
        "clusters": [],
        "summary": "",
        "participant_role": None,
        "company_name": None,
        "product_categories": [],
        "behavioral_segment": None,
        "demographics": None,
    }

    async def _raise_auth(*_a, **_kw):
        raise TeableAuthError("TEABLE_TOKEN rejected")

    # send_error is imported lazily inside the except branch, so patch it at its
    # real module path (`notifier.send_error`), not on discovery_extractor.
    with patch("discovery_extractor.asyncio.wait_for", side_effect=_raise_auth), \
         patch("discovery_extractor.TeableClient"), \
         patch("notifier.send_error", new=AsyncMock()) as mock_alert:
        result = await store_extraction_fn(
            pool=pool,
            extraction=extraction,
            participant_name="Test",
            interview_date=date(2026, 4, 16),
            transcript_text="text",
            fireflies_meeting_id="ff-123",
        )

    mock_alert.assert_awaited_once()
    title_arg = mock_alert.await_args.args[0]
    assert "Teable" in title_arg and "auth" in title_arg.lower()
    # Pipeline must succeed despite the auth failure
    assert result["interview_id"] == 42


def test_discovery_extractor_imports_without_fireflies_env(monkeypatch):
    """discovery_extractor must be importable in tooling (e.g. backfill_teable.py)
    that doesn't have FIREFLIES_API_KEY set. Regression: importing `notifier` at
    module top level pulled in config.py which requires FIREFLIES_API_KEY at
    import time and would KeyError before the module ever loaded.
    """
    import importlib
    import sys

    monkeypatch.delenv("FIREFLIES_API_KEY", raising=False)
    # Force a clean import of discovery_extractor (and its transitive deps) under
    # the cleared env. If anything at module-top-level reads FIREFLIES_API_KEY
    # strictly, the reload below will raise.
    for mod in ("discovery_extractor", "notifier", "config"):
        sys.modules.pop(mod, None)
    mod = importlib.import_module("discovery_extractor")
    assert hasattr(mod, "TeableAuthError")
    assert hasattr(mod, "store_extraction")
