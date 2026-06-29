"""Out-of-process decode pool (feature/sandbox prototype)."""

import io

import numpy as np
from PIL import Image

from imgedge.classifier.decode_pool import DecodePool


def _png(w, h):
    buf = io.BytesIO()
    arr = (np.random.default_rng(0).random((h, w, 3)) * 255).astype("uint8")
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def test_decode_returns_rgb_and_original_size():
    pool = DecodePool(workers=1, recycle=50, cap=1024)
    try:
        arr, ow, oh = pool.decode(_png(30, 20))
        assert (ow, oh) == (30, 20)
        assert arr.ndim == 3 and arr.shape[2] == 3
        assert arr.dtype == np.uint8
    finally:
        pool.close()


def test_decode_downscales_but_reports_original_size():
    pool = DecodePool(workers=1, recycle=50, cap=64)
    try:
        arr, ow, oh = pool.decode(_png(200, 100))
        assert (ow, oh) == (200, 100)                  # original size preserved
        assert max(arr.shape[0], arr.shape[1]) <= 64   # array itself is capped
    finally:
        pool.close()
