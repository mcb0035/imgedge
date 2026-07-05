# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Parity for the in-browser timm voter + ensemble.

Asserts the math the JS core (extension/inbrowser/timm.mjs + ensemble.mjs)
mirrors against the same fixture the JS test uses, so the two ports stay in
sync. Mirrors imgedge.voters.timm_voter.assess (softmax + signed evidence) and
imgedge.voters.base._combine (evidence sum + iNat override; salience deferred).
"""

import json
from pathlib import Path

import numpy as np

FIXTURE = Path(__file__).resolve().parent / "js" / "fixtures" / "timm_parity.json"
_FIX = json.loads(FIXTURE.read_text(encoding="utf-8"))
TOL = _FIX["tolerance"]


def test_preprocess_nchw():
    pp = _FIX["preprocess"]
    w, h, mean, std, rgba = pp["width"], pp["height"], pp["mean"], pp["std"], pp["rgba"]
    n = w * h
    got = [(rgba[p * 4 + c] / 255 - mean[c]) / std[c] for c in range(3) for p in range(n)]
    exp = pp["expected_nchw"]
    assert len(got) == len(exp)
    assert all(abs(a - b) <= TOL for a, b in zip(got, exp, strict=True))


def test_evidence():
    ev = _FIX["evidence"]
    z = np.array(ev["logits"], dtype=np.float64)
    probs = np.exp(z - z.max())
    probs /= probs.sum()
    pos = float(probs[ev["block_indices"]].sum())
    neg = float(probs[ev["contrast_indices"]].sum())
    evidence = pos - ev["contrast_weight"] * neg
    assert abs(pos - ev["expected_pos"]) <= TOL
    assert abs(neg - ev["expected_neg"]) <= TOL
    assert abs(evidence - ev["expected_evidence"]) <= TOL


def _combine(rows, threshold, inat_override):
    pos = sum(r["weight"] * r["evidence"] for r in rows if r["evidence"] > 0)
    neg = sum(r["weight"] * r["evidence"] for r in rows if r["evidence"] < 0)
    combined = max(0.0, min(1.0, pos + neg))
    inat = next((r for r in rows if r.get("isInat")), None)
    inat_score = inat.get("score") if inat else None
    override = inat_score is not None and inat_score >= inat_override
    if override:
        combined = max(combined, inat_score)
    return combined, bool(override or combined >= threshold)


def test_ensemble():
    en = _FIX["ensemble"]
    for case in en["cases"]:
        score, block = _combine(case["rows"], en["threshold"], en["inat_override"])
        assert abs(score - case["expected_score"]) <= TOL
        assert block == case["expected_block"]
