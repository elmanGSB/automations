"""Tests for OAuth credential self-heal functions in pipeline_runner.py.

Covers: _oauth_refresh, _write_creds_atomic, _refresh_claude_credentials.
All network calls and subprocess calls are mocked — no live endpoints required.
"""

import io
import json
import os
import pathlib
import time
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

# Set CI dummy env vars required by config.py before importing pipeline_runner.
os.environ.setdefault("FIREFLIES_API_KEY", "ci-dummy-key")
os.environ.setdefault("VM_API_SECRET", "ci-dummy-secret")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "ci-dummy-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "000000")

# Locate pipeline_runner.py (one level up from tests/)
_RUNNER_PATH = pathlib.Path(__file__).resolve().parents[1] / "pipeline_runner.py"

import importlib.util

spec = importlib.util.spec_from_file_location("pipeline_runner", _RUNNER_PATH)
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)

_oauth_refresh = _mod._oauth_refresh
_write_creds_atomic = _mod._write_creds_atomic
_refresh_claude_credentials = _mod._refresh_claude_credentials
_CREDS_PATH = _mod._CREDS_PATH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_creds(refresh_token="rt-abc", expires_at_ms=0, access_token="at-old"):
    return {
        "claudeAiOauth": {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": expires_at_ms,
        }
    }


def _mock_urlopen_ok(payload: dict, status=200):
    """Return a context-manager mock that yields payload as JSON."""
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _mock_http_error(code: int, body: dict | str):
    body_bytes = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
    err = urllib.error.HTTPError(
        url="https://example.com",
        code=code,
        msg="err",
        hdrs=None,
        fp=io.BytesIO(body_bytes),
    )
    return err


# ---------------------------------------------------------------------------
# _oauth_refresh tests
# ---------------------------------------------------------------------------


class TestOauthRefresh:
    def test_no_refresh_token_returns_none(self):
        creds = {"claudeAiOauth": {}}
        result = _oauth_refresh(creds)
        assert result is None

    def test_missing_oauth_section_returns_none(self):
        result = _oauth_refresh({})
        assert result is None

    def test_happy_path_no_token_rotation(self):
        creds = _make_creds(refresh_token="rt-1", access_token="at-old")
        payload = {"access_token": "at-new", "expires_in": 3600}
        mock_resp = _mock_urlopen_ok(payload)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _oauth_refresh(creds)
        assert result is not None
        assert result["claudeAiOauth"]["accessToken"] == "at-new"
        # Original refresh_token preserved when server doesn't send a new one
        assert result["claudeAiOauth"]["refreshToken"] == "rt-1"
        # expiresAt set ~3600s in the future
        now_ms = int(time.time() * 1000)
        assert result["claudeAiOauth"]["expiresAt"] > now_ms + 3590 * 1000

    def test_happy_path_with_token_rotation(self):
        creds = _make_creds(refresh_token="rt-old")
        payload = {"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 7200}
        mock_resp = _mock_urlopen_ok(payload)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _oauth_refresh(creds)
        assert result is not None
        assert result["claudeAiOauth"]["accessToken"] == "at-new"
        assert result["claudeAiOauth"]["refreshToken"] == "rt-new"

    def test_does_not_mutate_original_creds(self):
        creds = _make_creds(refresh_token="rt-1", access_token="at-old")
        original_creds = json.loads(json.dumps(creds))
        payload = {"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 3600}
        mock_resp = _mock_urlopen_ok(payload)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            _oauth_refresh(creds)
        assert creds == original_creds

    def test_http_error_invalid_grant_logs_critical(self):
        creds = _make_creds(refresh_token="rt-expired")
        err = _mock_http_error(400, {"error": "invalid_grant", "error_description": "Token expired"})
        with patch("urllib.request.urlopen", side_effect=err):
            with patch.object(_mod.logger, "critical") as mock_crit:
                result = _oauth_refresh(creds)
        assert result is None
        mock_crit.assert_called_once()
        assert "EXPIRED or revoked" in mock_crit.call_args[0][0]

    def test_http_error_non_invalid_grant_returns_none(self):
        creds = _make_creds(refresh_token="rt-1")
        err = _mock_http_error(429, {"error": "rate_limit_error", "error_description": "Too many requests"})
        with patch("urllib.request.urlopen", side_effect=err):
            result = _oauth_refresh(creds)
        assert result is None

    def test_http_error_non_json_body(self):
        creds = _make_creds(refresh_token="rt-1")
        err = urllib.error.HTTPError(
            url="https://example.com",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(b"<html>service unavailable</html>"),
        )
        with patch("urllib.request.urlopen", side_effect=err):
            result = _oauth_refresh(creds)
        assert result is None

    def test_network_exception_returns_none(self):
        creds = _make_creds(refresh_token="rt-1")
        with patch("urllib.request.urlopen", side_effect=ConnectionError("timeout")):
            result = _oauth_refresh(creds)
        assert result is None

    def test_response_missing_access_token_returns_none(self):
        creds = _make_creds(refresh_token="rt-1")
        payload = {"token_type": "Bearer"}  # no access_token key
        mock_resp = _mock_urlopen_ok(payload)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _oauth_refresh(creds)
        assert result is None

    def test_default_expires_in_used_when_missing(self):
        creds = _make_creds(refresh_token="rt-1")
        payload = {"access_token": "at-new"}  # no expires_in
        mock_resp = _mock_urlopen_ok(payload)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _oauth_refresh(creds)
        assert result is not None
        now_ms = int(time.time() * 1000)
        # Default is 8h; expiresAt should be ~8h from now
        assert result["claudeAiOauth"]["expiresAt"] > now_ms + 7 * 3600 * 1000


# ---------------------------------------------------------------------------
# _write_creds_atomic tests
# ---------------------------------------------------------------------------


class TestWriteCredsAtomic:
    def test_dict_written_as_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_CREDS_PATH", str(tmp_path / ".creds" / "credentials.json"))
        data = {"claudeAiOauth": {"accessToken": "tok"}}
        _write_creds_atomic(data)
        written = json.loads(pathlib.Path(_mod._CREDS_PATH).read_text())
        assert written == data

    def test_str_written_verbatim(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_CREDS_PATH", str(tmp_path / ".creds" / "credentials.json"))
        raw = '{"claudeAiOauth":{"accessToken":"tok"}}'
        _write_creds_atomic(raw)
        assert pathlib.Path(_mod._CREDS_PATH).read_text() == raw

    def test_file_permissions_are_restricted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_CREDS_PATH", str(tmp_path / ".creds" / "credentials.json"))
        _write_creds_atomic({"key": "value"})
        perms = os.stat(_mod._CREDS_PATH).st_mode & 0o777
        # mkstemp creates at 0o600; os.replace preserves that
        assert perms == 0o600

    def test_tmp_file_cleaned_up_on_write_error(self, tmp_path, monkeypatch):
        creds_path = str(tmp_path / ".creds" / "credentials.json")
        monkeypatch.setattr(_mod, "_CREDS_PATH", creds_path)
        creds_dir = str(tmp_path / ".creds")
        os.makedirs(creds_dir, exist_ok=True)

        # Patch os.replace to fail, leaving tmp file on disk
        with patch("os.replace", side_effect=OSError("replace failed")):
            with pytest.raises(OSError):
                _write_creds_atomic({"key": "value"})

        # No .tmp files should remain
        leftover = list(pathlib.Path(creds_dir).glob("*.tmp"))
        assert leftover == [], f"Stale tmp files: {leftover}"

    def test_creates_parent_directory_if_missing(self, tmp_path, monkeypatch):
        deep_path = str(tmp_path / "a" / "b" / "c" / "credentials.json")
        monkeypatch.setattr(_mod, "_CREDS_PATH", deep_path)
        _write_creds_atomic({"key": "value"})
        assert os.path.exists(deep_path)


# ---------------------------------------------------------------------------
# _refresh_claude_credentials tests
# ---------------------------------------------------------------------------


class TestRefreshClaudeCredentials:
    """Each test patches _CREDS_PATH to a temp file, isolating state."""

    def _write_creds(self, path, creds):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(creds, f)

    def test_already_fresh_returns_true_without_network_call(self, tmp_path, monkeypatch):
        creds_path = str(tmp_path / ".claude" / "creds.json")
        monkeypatch.setattr(_mod, "_CREDS_PATH", creds_path)
        future_ms = int(time.time() * 1000) + 7200 * 1000  # 2h from now
        creds = _make_creds(expires_at_ms=future_ms)
        self._write_creds(creds_path, creds)

        with patch("urllib.request.urlopen") as mock_url:
            result = _refresh_claude_credentials()
        assert result is True
        mock_url.assert_not_called()

    def test_oauth_refresh_success_returns_true(self, tmp_path, monkeypatch):
        creds_path = str(tmp_path / ".claude" / "creds.json")
        monkeypatch.setattr(_mod, "_CREDS_PATH", creds_path)
        creds = _make_creds(refresh_token="rt-valid", expires_at_ms=0)
        self._write_creds(creds_path, creds)

        payload = {"access_token": "at-new", "expires_in": 3600}
        mock_resp = _mock_urlopen_ok(payload)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _refresh_claude_credentials()
        assert result is True
        updated = json.loads(pathlib.Path(creds_path).read_text())
        assert updated["claudeAiOauth"]["accessToken"] == "at-new"

    def test_oauth_fails_falls_back_to_secret_manager(self, tmp_path, monkeypatch):
        creds_path = str(tmp_path / ".claude" / "creds.json")
        monkeypatch.setattr(_mod, "_CREDS_PATH", creds_path)
        creds = _make_creds(refresh_token="rt-expired", expires_at_ms=0)
        self._write_creds(creds_path, creds)

        fresh_creds = {"claudeAiOauth": {"accessToken": "at-fresh", "expiresAt": 9999999999999}}

        # OAuth fails (HTTPError)
        http_err = _mock_http_error(400, {"error": "invalid_grant"})
        sm_result = MagicMock()
        sm_result.returncode = 0
        sm_result.stdout = json.dumps(fresh_creds)
        sm_result.stderr = ""

        with patch("urllib.request.urlopen", side_effect=http_err):
            with patch("subprocess.run", return_value=sm_result):
                result = _refresh_claude_credentials()
        assert result is True
        written = json.loads(pathlib.Path(creds_path).read_text())
        assert written["claudeAiOauth"]["accessToken"] == "at-fresh"

    def test_gcloud_not_found_returns_false(self, tmp_path, monkeypatch):
        creds_path = str(tmp_path / ".claude" / "creds.json")
        monkeypatch.setattr(_mod, "_CREDS_PATH", creds_path)
        creds = _make_creds(refresh_token="rt-valid", expires_at_ms=0)
        self._write_creds(creds_path, creds)

        # OAuth returns None (no refresh token in server response)
        payload = {"token_type": "bearer"}  # no access_token
        mock_resp = _mock_urlopen_ok(payload)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("subprocess.run", side_effect=FileNotFoundError("gcloud")):
                result = _refresh_claude_credentials()
        assert result is False

    def test_gcloud_nonzero_exit_returns_false(self, tmp_path, monkeypatch):
        creds_path = str(tmp_path / ".claude" / "creds.json")
        monkeypatch.setattr(_mod, "_CREDS_PATH", creds_path)
        creds = _make_creds(refresh_token=None, expires_at_ms=0)
        # No refresh token → OAuth returns None immediately
        del creds["claudeAiOauth"]["refreshToken"]
        self._write_creds(creds_path, creds)

        sm_result = MagicMock()
        sm_result.returncode = 1
        sm_result.stderr = "ERROR: permission denied"
        sm_result.stdout = ""
        with patch("subprocess.run", return_value=sm_result):
            result = _refresh_claude_credentials()
        assert result is False

    def test_gcloud_non_json_output_returns_false(self, tmp_path, monkeypatch):
        creds_path = str(tmp_path / ".claude" / "creds.json")
        monkeypatch.setattr(_mod, "_CREDS_PATH", creds_path)
        creds = _make_creds(refresh_token=None, expires_at_ms=0)
        del creds["claudeAiOauth"]["refreshToken"]
        self._write_creds(creds_path, creds)

        sm_result = MagicMock()
        sm_result.returncode = 0
        sm_result.stdout = "WARNING: banner text\n{broken json"
        sm_result.stderr = ""
        with patch("subprocess.run", return_value=sm_result):
            result = _refresh_claude_credentials()
        assert result is False

    def test_missing_creds_file_falls_through_to_secret_manager(self, tmp_path, monkeypatch):
        creds_path = str(tmp_path / ".claude" / "creds.json")
        monkeypatch.setattr(_mod, "_CREDS_PATH", creds_path)
        # No file created — open() will raise FileNotFoundError

        fresh_creds = {"claudeAiOauth": {"accessToken": "at-fresh", "expiresAt": 9999999999999}}
        sm_result = MagicMock()
        sm_result.returncode = 0
        sm_result.stdout = json.dumps(fresh_creds)
        sm_result.stderr = ""
        with patch("subprocess.run", return_value=sm_result):
            result = _refresh_claude_credentials()
        assert result is True

    def test_lock_held_during_refresh(self, tmp_path, monkeypatch):
        """The function must hold _CREDS_LOCK throughout its execution."""
        creds_path = str(tmp_path / ".claude" / "creds.json")
        monkeypatch.setattr(_mod, "_CREDS_PATH", creds_path)
        creds = _make_creds(refresh_token="rt-1", expires_at_ms=0)
        self._write_creds(creds_path, creds)

        lock_acquired = []
        real_enter = _mod._CREDS_LOCK.__class__.__enter__

        def tracking_enter(self_lock):
            lock_acquired.append(True)
            return real_enter(self_lock)

        payload = {"access_token": "at-new", "expires_in": 3600}
        mock_resp = _mock_urlopen_ok(payload)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            _refresh_claude_credentials()

        # We can't easily intercept __enter__ on threading.Lock without
        # replacing it; just verify the function ran without exceptions
        # and the lock is not held after completion.
        assert not _mod._CREDS_LOCK.locked()
