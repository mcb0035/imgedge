# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Validate the committed deit3 in-browser voter config.

tools/export_timm_web.py bakes the deit3 third voter's preprocessing constants
and arachnid / contrast class indices into extension/inbrowser/deit3_web.json.
The indices are derived from the shared ImageNet-1k label order, so they must
match the timm voter's -- a mismatch means the export picked up a different
label set and the browser would score the wrong classes.
"""

import json
from pathlib import Path

INBROWSER = Path(__file__).resolve().parent.parent / "extension" / "inbrowser"
DEIT3 = json.loads((INBROWSER / "deit3_web.json").read_text(encoding="utf-8"))
TIMM = json.loads((INBROWSER / "timm_web.json").read_text(encoding="utf-8"))


def test_deit3_config_is_well_formed():
    assert DEIT3["model"] == "deit3_small_patch16_224"
    assert DEIT3["target"] == "Arachnida"
    assert DEIT3["num_classes"] == 1000
    assert DEIT3["weight"] == 0.75  # recall-max from the third-voter sweep

    inp = DEIT3["input"]
    assert inp["layout"] == "NCHW"
    assert inp["dtype"] == "float32"
    assert inp["softmax"] is True
    assert inp["height"] == inp["width"] == 224
    assert len(inp["mean"]) == len(inp["std"]) == 3
    assert 0.0 < inp["crop_pct"] <= 1.0


def test_deit3_indices_within_range():
    n = DEIT3["num_classes"]
    block = DEIT3["block_indices"]
    contrast = DEIT3["contrast_indices"]
    assert block and contrast
    assert all(0 <= i < n for i in block + contrast)


def test_deit3_shares_imagenet_indices_with_timm():
    # Same ImageNet-1k label order + same arachnid / contrast term lists => the
    # class indices (and contrast weight) must be identical to the timm voter's.
    assert DEIT3["block_indices"] == TIMM["block_indices"]
    assert DEIT3["contrast_indices"] == TIMM["contrast_indices"]
    assert DEIT3["contrast_weight"] == TIMM["contrast_weight"]
