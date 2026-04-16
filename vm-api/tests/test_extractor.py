import importlib



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
