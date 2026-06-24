"""Tests for claude-proxy.py error detection and HTTP response codes.

The proxy wraps `claude -p` as an Anthropic Messages API endpoint. The critical
behavior under test: when the claude CLI exits non-zero, the proxy must inspect
BOTH stderr AND stdout for auth phrases so the pipeline's auto-heal (401 →
refresh OAuth → retry) fires correctly even when the CLI writes its error to
stdout instead of stderr.
"""

import importlib.util
import json
import pathlib
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module bootstrap (claude-proxy.py has a hyphen — importlib required)
# ---------------------------------------------------------------------------

_PROXY_PATH = pathlib.Path(__file__).resolve().parents[1] / "claude-proxy.py"
spec = importlib.util.spec_from_file_location("claude_proxy", _PROXY_PATH)
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)
sys.modules.setdefault("claude_proxy", _mod)
ClaudeProxyHandler = _mod.ClaudeProxyHandler


# ---------------------------------------------------------------------------
# Fixture: ephemeral HTTP server
# ---------------------------------------------------------------------------

@pytest.fixture
def proxy_url():
    """Spin up ClaudeProxyHandler on a random free port; tear down after the test."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), ClaudeProxyHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PAYLOAD = json.dumps({
    "model": "claude-sonnet-4-6",
    "messages": [{"role": "user", "content": "hello"}],
}).encode()


def _post(url, payload=_PAYLOAD):
    req = urllib.request.Request(
        f"{url}/v1/messages",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _fake_result(returncode, stdout="", stderr=""):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


# ---------------------------------------------------------------------------
# Error detection tests
# ---------------------------------------------------------------------------

def test_stderr_auth_phrase_returns_401(proxy_url):
    """stderr contains an auth phrase → 401 (pre-existing behavior preserved)."""
    with patch("claude_proxy.subprocess.run", return_value=_fake_result(1, stderr="Error: oauth token expired")):
        status, body = _post(proxy_url)
    assert status == 401
    assert body["error"]["type"] == "authentication_error"


def test_stderr_non_auth_error_returns_502(proxy_url):
    """stderr contains a non-auth error → 502 (pre-existing behavior preserved)."""
    with patch("claude_proxy.subprocess.run", return_value=_fake_result(1, stderr="segfault")):
        status, body = _post(proxy_url)
    assert status == 502
    assert body["error"]["type"] == "api_error"


def test_stdout_auth_phrase_returns_401_when_stderr_blank(proxy_url):
    """Core bug fix: stderr blank + stdout contains auth phrase → 401, not 502.

    The claude CLI sometimes writes auth errors to stdout. Without the fix this
    returned 502, so the pipeline's auto-heal (OAuth refresh + retry) never fired.
    """
    with patch("claude_proxy.subprocess.run", return_value=_fake_result(1, stdout="not logged in", stderr="")):
        status, body = _post(proxy_url)
    assert status == 401
    assert body["error"]["type"] == "authentication_error"


def test_stdout_non_auth_content_returns_502_when_stderr_blank(proxy_url):
    """stderr blank + stdout has non-auth content → 502 (not a spurious 401)."""
    with patch("claude_proxy.subprocess.run", return_value=_fake_result(1, stdout="some other crash", stderr="")):
        status, body = _post(proxy_url)
    assert status == 502
    assert body["error"]["type"] == "api_error"


def test_both_blank_returns_502(proxy_url):
    """Both stderr and stdout blank on non-zero exit → 502."""
    with patch("claude_proxy.subprocess.run", return_value=_fake_result(1, stdout="", stderr="")):
        status, body = _post(proxy_url)
    assert status == 502
    assert body["error"]["type"] == "api_error"


def test_stderr_wins_when_both_contain_auth_phrase(proxy_url):
    """stderr non-blank takes precedence over stdout for the error message body."""
    with patch("claude_proxy.subprocess.run", return_value=_fake_result(
        1, stderr="oauth token expired", stdout="not logged in"
    )):
        status, body = _post(proxy_url)
    assert status == 401
    assert "oauth token expired" in body["error"]["message"]


def test_stdout_auth_phrase_detected_even_when_stderr_has_debug_line(proxy_url):
    """Both streams scanned: stderr has an innocuous debug line, stdout has the auth error.

    The original `(stderr or stdout)` short-circuit would see stderr and skip stdout,
    returning 502. The fix scans both, so the auth phrase in stdout triggers 401.
    """
    with patch("claude_proxy.subprocess.run", return_value=_fake_result(
        1, stderr="[debug] Claude Code v1.2.3", stdout="not logged in"
    )):
        status, body = _post(proxy_url)
    assert status == 401
    assert body["error"]["type"] == "authentication_error"


def test_returncode_zero_empty_stdout_returns_502(proxy_url):
    """returncode 0 with empty stdout → 502 (claude ran but produced nothing)."""
    with patch("claude_proxy.subprocess.run", return_value=_fake_result(0, stdout="")):
        status, body = _post(proxy_url)
    assert status == 502
    assert body["error"]["type"] == "api_error"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_success_returns_200_with_anthropic_shape(proxy_url):
    """returncode 0 + stdout has content → 200 with Anthropic message shape."""
    with patch("claude_proxy.subprocess.run", return_value=_fake_result(0, stdout="Hello!")):
        status, body = _post(proxy_url)
    assert status == 200
    assert body["type"] == "message"
    assert len(body["content"]) >= 1
    assert body["content"][0]["text"] == "Hello!"
