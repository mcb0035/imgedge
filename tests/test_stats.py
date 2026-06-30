"""Rolling latency stats accumulator (server.py)."""

import imgedge.classifier.server as server


def test_record_and_average():
    s = server.Stats()
    s.record(10.0, 30.0, blocked=True)
    s.record(20.0, 40.0, blocked=False)
    snap = s.snapshot()
    assert snap["n"] == 2
    assert snap["blocked"] == 1
    assert snap["infer_ms"] == 35.0  # (30 + 40) / 2
    assert snap["fetch_ms"] == 15.0  # (10 + 20) / 2
    assert snap["avg_ms"] == 50.0  # 40 + 60 / 2
    assert snap["max_ms"] == 60.0


def test_cache_hits_and_empty_snapshot():
    s = server.Stats()
    s.hit()
    s.hit()
    snap = s.snapshot()
    assert snap["cache_hits"] == 2
    assert snap["n"] == 0
    assert snap["avg_ms"] == 0  # no divide-by-zero with no model runs


def test_reset():
    s = server.Stats()
    s.record(5.0, 5.0, blocked=True)
    s.hit()
    s.reset()
    assert s.snapshot() == {
        "n": 0,
        "blocked": 0,
        "cache_hits": 0,
        "avg_ms": 0,
        "infer_ms": 0,
        "fetch_ms": 0,
        "max_ms": 0.0,
    }
