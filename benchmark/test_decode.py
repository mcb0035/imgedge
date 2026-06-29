"""Decode-path benchmarks: the guarded Pillow decode + RGB conversion + cap
resize that every classified image goes through (``decode_pool._decode`` and the
hardened ``open_guarded`` entry point).

This is the hottest CPU-bound step on the request path, so it is the most
valuable thing to track for regressions.
"""

import pytest
from _assets import encode

from imgedge.classifier.decode_pool import _decode
from imgedge.inat.inat_filter import open_guarded


@pytest.mark.parametrize(
    "fmt,side",
    [
        ("JPEG", 256),
        ("JPEG", 1280),
        ("PNG", 256),
        ("PNG", 1280),
    ],
    ids=["jpeg-256", "jpeg-1280", "png-256", "png-1280"],
)
def test_decode_to_rgb_array(benchmark, fmt, side):
    """Full decode -> RGB uint8 array, downscaled to the 1024px cap (the exact
    work a decode worker performs per image)."""
    kwargs = {"quality": 85} if fmt == "JPEG" else {}
    raw = encode(side, fmt=fmt, **kwargs)
    arr, ow, oh = benchmark(_decode, raw, 1024)
    assert arr.dtype.itemsize == 1 and arr.ndim == 3
    assert (ow, oh) == (side, side)


def test_open_guarded_header_only(benchmark):
    """Decode hardening / header parse alone (no full rasterisation), the cheap
    guard that runs before every decode."""
    raw = encode(1280, fmt="JPEG", quality=85)

    def open_and_close():
        with open_guarded(raw) as img:
            return img.size

    size = benchmark(open_and_close)
    assert size == (1280, 1280)
