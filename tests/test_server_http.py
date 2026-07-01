"""HTTP-layer tests for the classifier server: token auth, the request-body cap,
path routing, and the `/health` challenge proof.

These drive the real ``PooledHTTPServer`` on an ephemeral loopback port with
``classify`` stubbed and the ensemble forced absent, so no model download or
network egress is needed. The server + every response socket is closed on
teardown so the suite stays clean under ``-W error`` (filterwarnings=error).
"""

import hashlib
import hmac
import json
import threading
import urllib.error
import urllib.request

import pytest

import imgedge.classifier.server as server

TOKEN = "test-token-http"


def _request(url, method="GET", token=None, body=None):
    """Make one request and return (status_code, parsed_json_body)."""
    headers = {}
    data = None
    if body is not None:
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-ImgEdge-Token"] = token
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        finally:
            exc.close()


@pytest.fixture
def live_server(monkeypatch):
    """A running server on 127.0.0.1:<ephemeral> with a known token, no model, and
    a stubbed classify(); yields the base URL and tears the server down cleanly."""
    monkeypatch.setattr(server, "TOKEN", TOKEN)
    monkeypatch.setattr(server, "ensure_ensemble", lambda: None)
    monkeypatch.setattr(server, "classify", lambda *a, **k: {"block": True, "reason": "stub", "score": 0.9})

    httpd = server.PooledHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_health_unauthenticated_is_minimal(live_server):
    status, payload = _request(f"{live_server}/health")
    assert status == 200
    assert set(payload) == {"status", "model", "auth_required"}


def test_health_authenticated_has_detail(live_server):
    status, payload = _request(f"{live_server}/health", token=TOKEN)
    assert status == 200
    assert payload["auth_required"] is True
    assert "target" in payload and "voters" in payload  # token-gated fields


def test_health_challenge_returns_token_proof(live_server):
    # The proof is added whenever a challenge is present (no token required) so the
    # extension can confirm the server knows the token before disclosing it (F2).
    status, payload = _request(f"{live_server}/health?challenge=nonce-xyz")
    assert status == 200
    expected = hmac.new(TOKEN.encode("utf-8"), b"nonce-xyz", hashlib.sha256).hexdigest()
    assert payload["proof"] == expected


def test_classify_without_token_is_unauthorized(live_server):
    status, payload = _request(f"{live_server}/classify", method="POST", body={"url": "http://e/x.jpg"})
    assert status == 401
    assert payload == {"error": "unauthorized"}


def test_classify_with_token_returns_verdict(live_server):
    status, payload = _request(f"{live_server}/classify", method="POST", token=TOKEN, body={"url": "http://e/x.jpg"})
    assert status == 200
    assert payload == {"block": True, "reason": "stub", "score": 0.9}


def test_classify_body_too_large_is_rejected(live_server, monkeypatch):
    monkeypatch.setattr(server, "MAX_BODY_BYTES", 16)
    status, payload = _request(f"{live_server}/classify", method="POST", token=TOKEN, body={"url": "x" * 200})
    assert status == 413
    assert payload == {"error": "payload too large"}


def test_unknown_get_path_is_404(live_server):
    status, _ = _request(f"{live_server}/nope")
    assert status == 404


def test_unknown_post_path_is_404(live_server):
    status, _ = _request(f"{live_server}/nope", method="POST", token=TOKEN, body={})
    assert status == 404
