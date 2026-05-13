import importlib


def test_hindsight_url_reads_env(monkeypatch):
    """HINDSIGHT_URL must be overridable via env var."""
    monkeypatch.setenv("HINDSIGHT_URL", "http://127.0.0.1:8888")
    import hindsight
    importlib.reload(hindsight)
    assert hindsight.HINDSIGHT_URL == "http://127.0.0.1:8888"


def test_hindsight_url_default_is_loopback(monkeypatch):
    """HINDSIGHT_URL defaults to VM-internal loopback when env var unset."""
    monkeypatch.delenv("HINDSIGHT_URL", raising=False)
    import hindsight
    importlib.reload(hindsight)
    assert hindsight.HINDSIGHT_URL == "http://127.0.0.1:8888"
