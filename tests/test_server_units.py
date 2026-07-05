# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for server.py branches the HTTP-level tests don't reach: the
`classify()` fetch-failed / exception / success paths, the `health_payload`
detail vs. liveness branches, and two small helpers (`_clamp01`, the inline
data-URL path of `fetch_image_bytes`). Everything is mocked — no real image
bytes and no network — so the suite stays image-free and offline.
"""

import json

import imgedge.classifier.server as server


class _FakeVoter:
    def __init__(self, name):
        self.name = name


class _FakeEns:
    policy = "evidence"
    inat = None

    def __init__(self, names, verdict=None, raises=False):
        self.voters = [_FakeVoter(n) for n in names]
        self._verdict = verdict or {"block": True, "reason": "unit", "score": 0.5}
        self._raises = raises

    @property
    def names(self):
        return [v.name for v in self.voters]

    def classify_bytes(self, raw, meta, decoder, threshold, salience, only=None):
        if self._raises:
            raise RuntimeError("internal detail that must not leak to the client")
        return self._verdict


# ---- _clamp01 --------------------------------------------------------------
def test_clamp01_clamps_and_rejects_non_numeric():
    assert server._clamp01(None) is None
    assert server._clamp01(0.5) == 0.5
    assert server._clamp01(2) == 1.0  # clamped to max
    assert server._clamp01(-3) == 0.0  # clamped to min
    assert server._clamp01("nope") is None  # non-numeric -> None (ValueError)
    assert server._clamp01([1, 2]) is None  # non-numeric -> None (TypeError)


# ---- fetch_image_bytes: inline data-URL error paths (no network) -----------
def test_fetch_image_bytes_malformed_data_url_returns_none():
    assert server.fetch_image_bytes(None, "data:image/png;base64") is None  # no comma -> IndexError
    assert server.fetch_image_bytes(None, "data:image/png;base64,@@@not-base64@@@") is None


# ---- classify() branches ---------------------------------------------------
def test_classify_model_unavailable(monkeypatch):
    monkeypatch.setattr(server, "ensure_ensemble", lambda: None)
    assert server.classify("http://x/1.jpg", None) == {
        "block": False,
        "reason": "model-unavailable",
        "score": 0.0,
    }


def test_classify_fetch_failed(monkeypatch):
    monkeypatch.setattr(server, "ensure_ensemble", lambda: _FakeEns(["inat:a"]))
    monkeypatch.setattr(server, "fetch_image_bytes", lambda url, data: None)
    assert server.classify("http://x/2.jpg", None) == {
        "block": False,
        "reason": "fetch-failed",
        "score": 0.0,
    }


def test_classify_exception_returns_generic_reason(monkeypatch):
    monkeypatch.setattr(server, "ensure_ensemble", lambda: _FakeEns(["inat:a"], raises=True))
    monkeypatch.setattr(server, "fetch_image_bytes", lambda url, data: b"raw-not-an-image")
    res = server.classify("http://x/3.jpg", None)
    # Generic reason only — the internal exception text must not leak.
    assert res == {"block": False, "reason": "error", "score": 0.0}


def test_classify_success_returns_verdict(monkeypatch):
    ens = _FakeEns(["inat:a"], verdict={"block": True, "reason": "unit", "score": 0.7})
    monkeypatch.setattr(server, "ensure_ensemble", lambda: ens)
    monkeypatch.setattr(server, "fetch_image_bytes", lambda url, data: b"raw-not-an-image")
    res = server.classify("http://x/unique-success.jpg", None)
    assert res == {"block": True, "reason": "unit", "score": 0.7}


# ---- health_payload() ------------------------------------------------------
def test_health_payload_offline_detail(monkeypatch):
    monkeypatch.setattr(server, "ensure_ensemble", lambda: None)
    p = server.health_payload(full=True)
    assert p["status"] == "model-missing"
    assert p["model"] is False
    assert p["voters"] == []
    assert p["profiles"] == {}
    assert p["taxa"] == 0


def test_health_payload_full_with_ensemble(monkeypatch):
    monkeypatch.setattr(server, "ensure_ensemble", lambda: _FakeEns(["inat:a", "timm:b"]))
    p = server.health_payload(full=True)
    assert p["status"] == "ok"
    assert p["model"] is True
    assert p["voters"] == ["inat:a", "timm:b"]
    assert set(p["profiles"]) == {"fast", "balanced", "accurate"}
    assert p["policy"] == "evidence"


# ---- classify(): per-override cache key + cache hit ------------------------
def test_classify_overrides_use_dedicated_key_and_cache_hit(monkeypatch):
    ens = _FakeEns(["inat:a"], verdict={"block": False, "reason": "unit", "score": 0.1})
    monkeypatch.setattr(server, "ensure_ensemble", lambda: ens)
    fetches = {"n": 0}

    def _fetch(url, data):
        fetches["n"] += 1
        return b"raw-not-an-image"

    monkeypatch.setattr(server, "fetch_image_bytes", _fetch)
    url = "http://x/override-cache-unit.jpg"
    first = server.classify(url, None, threshold=0.3, salience=0.5)
    second = server.classify(url, None, threshold=0.3, salience=0.5)
    assert first == second == {"block": False, "reason": "unit", "score": 0.1}
    assert fetches["n"] == 1  # second call served from the verdict cache, not re-fetched


# ---- VerdictCache: disk round-trip, corrupt file, cap trim -----------------
def test_verdict_cache_round_trips_via_disk(tmp_path):
    p = tmp_path / "cache.json"
    c = server.VerdictCache(p, cap=10, flush_every=1)
    c.put("http://x/a.jpg", {"block": True})
    assert p.exists()  # flush_every=1 -> _flush_locked wrote the file
    reloaded = server.VerdictCache(p, cap=10)
    assert reloaded.get("http://x/a.jpg") == {"block": True}


def test_verdict_cache_ignores_corrupt_file(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ this is not valid json", encoding="utf-8")
    c = server.VerdictCache(p)  # _load swallows the ValueError -> empty cache
    assert c.get("http://x/a.jpg") is None


def test_verdict_cache_trims_to_cap_on_load(tmp_path):
    p = tmp_path / "big.json"
    p.write_text(json.dumps({f"k{i}": {"block": False} for i in range(20)}), encoding="utf-8")
    c = server.VerdictCache(p, cap=5)  # _load trims the oldest entries down to cap
    assert len(c._data) == 5


# ---- _verify_pinned: model-integrity check ---------------------------------
def test_verify_pinned_rejects_hash_mismatch(monkeypatch, tmp_path):
    import imgedge.inat.download_models as dm

    f = tmp_path / "model.tflite"
    f.write_bytes(b"tampered bytes")
    monkeypatch.setattr(dm, "CHECKSUMS", {"model.tflite": "0" * 64}, raising=False)
    monkeypatch.setattr(dm, "sha256_of", lambda path: "f" * 64, raising=False)
    assert server._verify_pinned(f) is False  # known name, wrong hash -> refused


def test_verify_pinned_passes_unpinned_name(monkeypatch, tmp_path):
    import imgedge.inat.download_models as dm

    f = tmp_path / "custom-model.tflite"
    f.write_bytes(b"anything")
    monkeypatch.setattr(dm, "CHECKSUMS", {}, raising=False)
    assert server._verify_pinned(f) is True  # no pin for this name -> allowed


# ---- _env_ports: fetch-port allowlist parsing ------------------------------
def test_env_ports_parsing():
    assert server._env_ports("") is None
    assert server._env_ports("any") is None
    assert server._env_ports("*") is None
    assert server._env_ports("80,443") == {80, 443}
    assert server._env_ports("8080, bad, 443") == {8080, 443}  # non-digit entries skipped
    assert server._env_ports("nope") is None  # no digits -> None


# ---- _host_allowed: optional egress allowlist ------------------------------
def test_host_allowed_respects_allowlist(monkeypatch):
    monkeypatch.setattr(server, "ALLOW_HOSTS", ("example.com",))
    assert server._host_allowed("example.com") is True
    assert server._host_allowed("img.example.com") is True  # subdomain of an allowed host
    assert server._host_allowed("evil.org") is False
    monkeypatch.setattr(server, "ALLOW_HOSTS", ())
    assert server._host_allowed("anything.example") is True  # empty allowlist -> allow all
