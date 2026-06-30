"""Hardening fixes from docs/threat-model.md (server-side units: F1-F5, F8, F11)."""

import hashlib
import hmac
import os

import imgedge.classifier.server as server


def test_request_timeout_set():  # F1 — slowloris guard
    assert server.Handler.timeout and server.Handler.timeout > 0


def test_fetch_ua_is_neutral():  # F3 — no "ImgEdge" tell to image hosts
    assert "imgedge" not in server.FETCH_UA.lower()


def test_health_minimal_is_lean():  # F4 — unauthenticated callers get only liveness
    minimal = server.health_payload(full=False)
    assert set(minimal) == {"status", "model", "auth_required"}
    for leaky in ("provider", "backend", "target", "stats", "voters", "sandbox"):
        assert leaky not in minimal


def test_health_full_has_details():  # F4
    full = server.health_payload(full=True)
    assert "target" in full and "provider" in full and full["auth_required"] is True


def test_health_proof_is_token_hmac():  # F2 — server proves it knows the token
    proof = server._health_proof("nonce-123")
    assert proof == hmac.new(server.TOKEN.encode(), b"nonce-123", hashlib.sha256).hexdigest()
    assert server._health_proof("a") != server._health_proof("b")  # challenge-bound


def test_cache_key_is_keyed_hmac():  # F5 — not a precomputable plain SHA-256
    c = server.VerdictCache(None)
    k = c._key("http://example.com/x.png")
    assert k != hashlib.sha256(b"http://example.com/x.png").hexdigest()
    assert k == hmac.new(server._CACHE_HMAC_KEY, b"http://example.com/x.png",
                         hashlib.sha256).hexdigest()


def test_cache_roundtrip():  # F5 sanity — keying didn't break get/put
    c = server.VerdictCache(None)
    c.put("http://h/x", {"block": True})
    assert c.get("http://h/x") == {"block": True}


def test_token_file_atomic_and_restrictive(tmp_path, monkeypatch):  # F8
    tf = tmp_path / "tok"
    monkeypatch.delenv("IMGEDGE_TOKEN", raising=False)
    monkeypatch.setenv("IMGEDGE_TOKEN_FILE", str(tf))
    t1 = server.load_or_create_token()
    assert t1 and tf.exists()
    assert server.load_or_create_token() == t1  # persisted, not clobbered
    if hasattr(os, "getuid"):  # POSIX perms only
        assert tf.stat().st_mode & 0o077 == 0  # not group/other-accessible


def test_classify_error_is_generic(monkeypatch):  # F11 — no internals leaked to client
    class Boom:
        def classify_bytes(self, *a, **k):
            raise RuntimeError("secret /etc/internal/path")

    monkeypatch.setattr(server, "ensure_ensemble", lambda: Boom())
    out = server.classify("http://x/never-cached-uniq", "data:image/png;base64,AAAA", None)
    assert out["reason"] == "error"
    assert "secret" not in str(out) and "/etc/" not in str(out)
