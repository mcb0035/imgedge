"""Verdict cache: LRU eviction, recency, persistence, hashed keys (server.py)."""

import server


def test_lru_eviction(tmp_path):
    c = server.VerdictCache(tmp_path / "c.json", cap=2, flush_every=1000)
    c.put("a", {"block": False})
    c.put("b", {"block": True})
    c.put("c", {"block": False})  # evicts the least-recently-used "a"
    assert c.get("a") is None
    assert c.get("b") == {"block": True}
    assert c.get("c") == {"block": False}


def test_get_refreshes_recency(tmp_path):
    c = server.VerdictCache(tmp_path / "c.json", cap=2, flush_every=1000)
    c.put("a", {"x": 1})
    c.put("b", {"x": 2})
    assert c.get("a") == {"x": 1}   # touch "a" so "b" becomes the LRU entry
    c.put("c", {"x": 3})            # evicts "b"
    assert c.get("b") is None
    assert c.get("a") == {"x": 1}


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "c.json"
    first = server.VerdictCache(path, cap=10, flush_every=1)
    first.put("https://x/y.png", {"block": True, "score": 0.9})
    first.flush()
    second = server.VerdictCache(path, cap=10)
    assert second.get("https://x/y.png") == {"block": True, "score": 0.9}


def test_key_is_hashed_not_the_url():
    key = server.VerdictCache._key("https://example.com/secret.png")
    assert key != "https://example.com/secret.png"
    assert len(key) == 64  # sha-256 hex; the raw URL never touches disk


def test_empty_url_is_ignored(tmp_path):
    c = server.VerdictCache(tmp_path / "c.json")
    c.put("", {"block": True})
    assert c.get("") is None
