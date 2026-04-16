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


def make_mock_pool():
    pool = MagicMock(spec=asyncpg.Pool)
    pool.fetchrow = AsyncMock(return_value=None)
    pool.fetchval = AsyncMock(return_value=42)
    pool.execute = AsyncMock()
    return pool


@pytest.mark.asyncio
async def test_store_extraction_uses_injected_pool():
    """store_extraction must use the passed pool, not create its own."""
    from discovery_extractor import store_extraction

    mock_pool = make_mock_pool()
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
         patch("discovery_extractor.TeableClient") as mock_teable:
        mock_teable.return_value.write_interview = MagicMock(return_value=1)
        mock_teable.return_value.write_insights = MagicMock(return_value=0)
        mock_teable.return_value.write_clusters = MagicMock(return_value=0)

        result = await store_extraction(
            pool=mock_pool,
            extraction=extraction,
            participant_name="John",
            interview_date=date(2026, 4, 16),
            transcript_text="Hello world",
        )

    # asyncpg.create_pool must NOT have been called
    mock_asyncpg.create_pool.assert_not_called()
    # The injected pool must have been used for the INSERT ... RETURNING id
    mock_pool.fetchval.assert_awaited_once()
    assert result["interview_id"] == 42


@pytest.mark.asyncio
async def test_process_discovery_meeting_threads_pool():
    """process_discovery_meeting must accept and thread pool through."""
    from discovery_extractor import process_discovery_meeting

    mock_pool = make_mock_pool()

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
            pool=mock_pool,
            transcript_text="text",
            participant_name="Jane",
            meeting_date="2026-04-16",
        )

    # store_extraction must have received the pool
    call = mock_store.call_args
    passed_pool = call.kwargs.get("pool") or (call.args[0] if call.args else None)
    assert passed_pool is mock_pool
