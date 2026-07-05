# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Parity guard: the committed JS fixture must match the real Python pipeline.

The in-browser classifier (extension/inbrowser/inat.mjs) re-implements
inat_filter.prep_input / postprocess in JavaScript. Both the Node parity test
(tests/js/inbrowser_parity.test.mjs) and this test assert against
tests/js/fixtures/inat_parity.json, pinning the two ports to one reference so
they cannot silently diverge.
"""

import json
from pathlib import Path

import numpy as np

from imgedge.inat.inat_filter import postprocess

FIXTURE = Path(__file__).resolve().parent / "js" / "fixtures" / "inat_parity.json"


def _fixture():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def test_preprocess_matches_fixture():
    root = _fixture()
    fx = root["preprocess"]
    rgba = np.array(fx["rgba"], dtype=np.float32).reshape(-1, 4)
    rgb = rgba[:, :3]  # drop alpha, same as prep_input's RGB input
    got = ((rgb / np.float32(fx["divisor"])) + np.float32(fx["offset"])).astype(np.float32).flatten()
    np.testing.assert_allclose(got, fx["expected_nhwc"], atol=root["tolerance"])


def test_postprocess_matches_fixture():
    root = _fixture()
    fx = root["postprocess"]
    out = np.array(fx["output"], dtype=np.float32)
    mask = np.zeros(fx["num_classes"], dtype=bool)
    mask[fx["arachnida_leaf_indices"]] = True
    got = postprocess(out, mask)
    assert abs(got - fx["expected_score"]) <= root["tolerance"]
