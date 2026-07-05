# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""AppContainer decode pool — opt-in (Windows, sets up icacls grants).

Skipped by default so the normal suite and Linux CI stay fast and green. Run on
Windows with:  $env:IMGEDGE_TEST_APPCONTAINER=1; pytest tests/test_appcontainer_pool.py
"""

import io
import os
import sys

import numpy as np
import pytest
from PIL import Image

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("IMGEDGE_TEST_APPCONTAINER") != "1",
    reason="AppContainer pool test is Windows-only and opt-in (set IMGEDGE_TEST_APPCONTAINER=1)",
)


def _png(w, h):
    buf = io.BytesIO()
    arr = (np.random.default_rng(0).random((h, w, 3)) * 255).astype("uint8")
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def test_decode_and_isolation():
    from imgedge.classifier.ac_pool import AppContainerPool

    pool = AppContainerPool(workers=2, recycle=5, cap=1024)  # 2 workers: per-worker mem cap
    try:
        assert pool.confined  # Job object attached
        arr, ow, oh = pool.decode(_png(30, 20))
        assert (ow, oh) == (30, 20)  # original size preserved
        assert arr.ndim == 3 and arr.shape[2] == 3
        assert arr.dtype == np.uint8
        # the security guarantee: from inside the container, both are denied
        rep = pool.probe()
        assert rep.get("network", "").startswith("DENIED"), rep
        assert rep.get("write", "").startswith("DENIED"), rep
    finally:
        pool.close()


def test_downscale_reports_original_size():
    from imgedge.classifier.ac_pool import AppContainerPool

    pool = AppContainerPool(workers=1, recycle=5, cap=64)
    try:
        arr, ow, oh = pool.decode(_png(200, 100))
        assert (ow, oh) == (200, 100)
        assert max(arr.shape[0], arr.shape[1]) <= 64
    finally:
        pool.close()


def test_recycle_and_self_heal():
    from imgedge.classifier.ac_pool import AppContainerPool

    pool = AppContainerPool(workers=1, recycle=2, cap=256)
    try:
        for _ in range(6):  # crosses the recycle threshold several times
            arr, ow, oh = pool.decode(_png(40, 40))
            assert (ow, oh) == (40, 40)
            assert arr.dtype == np.uint8
    finally:
        pool.close()
