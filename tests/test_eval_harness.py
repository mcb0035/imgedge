"""Tests for the evaluation harness pure logic (no models, no network needed).

The encrypted-zip round-trip is skipped when pyzipper isn't installed (the CI
test job uses only the base deps), so the suite runs everywhere.
"""

import io
import json
import math

import eval_filter
import pytest
from PIL import Image


def test_metrics_basic():
    m = eval_filter.metrics(tp=8, fp=1, tn=9, fn=2)
    assert m["recall"] == 0.8
    assert m["fpr"] == 0.1
    assert m["precision"] == 8 / 9
    assert (m["pos"], m["neg"], m["n"]) == (10, 10, 20)


def test_metrics_empty_is_nan():
    m = eval_filter.metrics(0, 0, 0, 0)
    assert math.isnan(m["recall"]) and math.isnan(m["fpr"])


def test_confusion_threshold_vs_default():
    records = [
        {"label": "block", "combined": 0.8, "block": True},
        {"label": "block", "combined": 0.3, "block": False},
        {"label": "allow", "combined": 0.6, "block": True},
        {"label": "allow", "combined": 0.1, "block": False},
    ]
    assert eval_filter.confusion(records, 0.5) == (1, 1, 1, 1)
    assert eval_filter.confusion(records, None) == (1, 1, 1, 1)


def test_sweep_recall_monotonic():
    records = [{"label": "block", "combined": c, "block": c >= 0.5} for c in (0.2, 0.4, 0.6, 0.8)]
    recalls = [r["recall"] for r in eval_filter.sweep(records, [0.1, 0.5, 0.9])]
    assert recalls[0] >= recalls[1] >= recalls[2]


def test_salience_boost_only_recovers_suppressed():
    records = [
        {"label": "block", "pos": 0.6, "neg": 0.0, "mult": 0.5},
        {"label": "block", "pos": 0.9, "neg": 0.0, "mult": 1.2},
        {"label": "allow", "pos": 0.1, "neg": -0.2, "mult": 1.0},
    ]
    out = eval_filter.salience_variants(records, 0.5)
    assert out["_n_usable"] == 3
    assert out["boost_only"]["recall"] >= out["baseline"]["recall"]


def test_misses_split_and_order():
    records = [
        {
            "label": "block",
            "combined": 0.20,
            "block": False,
            "name": "block/miss.jpg",
            "pos": 0.2,
            "neg": 0.0,
            "mult": 1.0,
        },
        {
            "label": "allow",
            "combined": 0.90,
            "block": True,
            "name": "allow/oops.jpg",
            "pos": 0.9,
            "neg": 0.0,
            "mult": 1.0,
        },
        {
            "label": "block",
            "combined": 0.95,
            "block": True,
            "name": "block/ok.jpg",
            "pos": 0.95,
            "neg": 0.0,
            "mult": 1.0,
        },
    ]
    fns, fps = eval_filter.misses(records, None)
    assert [r["name"] for r in fns] == ["block/miss.jpg"]
    assert [r["name"] for r in fps] == ["allow/oops.jpg"]


def test_iter_dir(tmp_path):
    for label, color in (("block", (200, 30, 30)), ("allow", (30, 30, 200))):
        d = tmp_path / label
        d.mkdir()
        Image.new("RGB", (8, 8), color).save(d / "x.png")
    got = sorted((lbl, name) for lbl, name, _ in eval_filter._iter_dir(tmp_path))
    assert got == [("allow", "allow/x.png"), ("block", "block/x.png")]


def test_encrypted_zip_roundtrip(tmp_path):
    pytest.importorskip("pyzipper")
    entries = {}
    for arc in ("block/a.png", "allow/b.png"):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
        entries[arc] = buf.getvalue()
    zpath = tmp_path / "d.eval.zip"
    eval_filter._write_zip(str(zpath), "pw123", entries.items())
    got = sorted((lbl, name) for lbl, name, _ in eval_filter.iter_samples(str(zpath), "pw123"))
    assert got == [("allow", "allow/b.png"), ("block", "block/a.png")]


def test_build_synthetic_roundtrip(tmp_path):
    pytest.importorskip("pyzipper")
    zpath = tmp_path / "syn.eval.zip"
    eval_filter.build_synthetic(str(zpath), "pw123", count=3, seed=7)
    labels = [lbl for lbl, _, _ in eval_filter.iter_samples(str(zpath), "pw123")]
    assert labels.count("block") == 3
    assert labels.count("allow") == 3


def test_fmt_dur():
    assert eval_filter._fmt_dur(45) == "45s"
    assert eval_filter._fmt_dur(80) == "1m20s"
    assert eval_filter._fmt_dur(3720) == "1h02m"


def test_percentiles_empty_and_basic():
    assert eval_filter._percentiles([]) == {}
    p = eval_filter._percentiles([10, 20, 30, 40])
    assert p["n"] == 4 and p["mean"] == 25.0 and p["max"] == 40


def test_latency_summary_excludes_skipped_voters():
    records = [
        {"decision_ms": 10.0, "voter_ms": {"a": 4.0, "b": 0}},
        {"decision_ms": 20.0, "voter_ms": {"a": 6.0, "b": 0}},
    ]
    lat = eval_filter._latency_summary(records)
    assert lat["decision_ms"]["n"] == 2
    assert "a" in lat["per_voter_ms"]  # ran
    assert "b" not in lat["per_voter_ms"]  # skipped (0 ms) -> excluded


def test_build_inat_routes_by_class(tmp_path):
    pytest.importorskip("pyzipper")
    imgs = tmp_path / "imgs"
    (imgs / "val/araneae").mkdir(parents=True)
    (imgs / "val/aves").mkdir(parents=True)
    Image.new("RGB", (8, 8), (200, 0, 0)).save(imgs / "val/araneae/a.jpg", "JPEG")
    Image.new("RGB", (8, 8), (0, 0, 200)).save(imgs / "val/aves/b.jpg", "JPEG")
    meta = {
        "categories": [{"id": 1, "class": "Arachnida"}, {"id": 2, "class": "Aves"}],
        "images": [
            {"id": 10, "file_name": "val/araneae/a.jpg"},
            {"id": 11, "file_name": "val/aves/b.jpg"},
        ],
        "annotations": [
            {"id": 1, "image_id": 10, "category_id": 1},
            {"id": 2, "image_id": 11, "category_id": 2},
        ],
    }
    mpath = tmp_path / "val.json"
    mpath.write_text(json.dumps(meta), encoding="utf-8")
    zpath = tmp_path / "inat.eval.zip"
    eval_filter.build_inat(str(imgs), str(mpath), str(zpath), "pw", limit_per_class=10, seed=1)
    labels = sorted(lbl for lbl, _, _ in eval_filter.iter_samples(str(zpath), "pw"))
    assert labels == ["allow", "block"]


def test_sampling_selects_n_per_class(tmp_path):
    pytest.importorskip("pyzipper")
    entries = {}
    for i in range(5):
        for label in ("block", "allow"):
            buf = io.BytesIO()
            Image.new("RGB", (8, 8), (i * 10, 0, 0)).save(buf, format="PNG")
            entries[f"{label}/{i}.png"] = buf.getvalue()
    zpath = tmp_path / "s.eval.zip"
    eval_filter._write_zip(str(zpath), "pw", entries.items())
    assert len(list(eval_filter._labeled_names(str(zpath), "pw"))) == 10
    only = eval_filter._sample_names(str(zpath), "pw", 2, seed=1)
    assert len(only) == 4
    got = sorted(lbl for lbl, _, _ in eval_filter.iter_samples(str(zpath), "pw", only))
    assert got == ["allow", "allow", "block", "block"]


def test_build_openimages_routes_by_label(tmp_path):
    pytest.importorskip("pyzipper")
    imgs = tmp_path / "oi"
    imgs.mkdir()
    for stem in ("a", "b", "c"):
        Image.new("RGB", (8, 8), (10, 10, 10)).save(imgs / f"{stem}.jpg", "JPEG")
    (tmp_path / "desc.csv").write_text("/m/09kmb,Spider\n/m/0xxx,Cat\n", encoding="utf-8")
    (tmp_path / "labels.csv").write_text(
        "ImageID,Source,LabelName,Confidence\n"
        "a,verification,/m/09kmb,1\n"
        "b,verification,/m/0xxx,1\n"
        "c,verification,/m/0xxx,0\n",
        encoding="utf-8",
    )
    out = tmp_path / "oi.eval.zip"
    eval_filter.build_openimages(str(imgs), str(tmp_path / "labels.csv"), str(tmp_path / "desc.csv"), str(out), "pw")
    got = sorted((lbl, name) for lbl, name, _ in eval_filter.iter_samples(str(out), "pw"))
    assert got == [("allow", "allow/b.jpg"), ("block", "block/a.jpg")]


def test_classify_sample_resilient_to_failure():
    class _Boom:
        def classify_bytes(self, *a, **k):
            raise ValueError("image too large")

    rec = eval_filter.classify_sample(_Boom(), b"x")
    assert rec["error"] is True
    assert rec["block"] is False
    assert rec["combined"] == 0.0
