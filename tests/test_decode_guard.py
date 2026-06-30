"""open_guarded decode hardening: large-image downscale + reject ceilings."""

import io

import pytest
from PIL import Image

import imgedge.inat.inat_filter as f
from imgedge.inat.inat_filter import open_guarded


def _bytes(w, h, fmt):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (123, 50, 30)).save(buf, format=fmt)
    return buf.getvalue()


def test_normal_image_passes():
    with open_guarded(_bytes(320, 240, "JPEG")) as img:
        assert img.size == (320, 240)


def test_large_jpeg_is_downscaled_not_rejected(monkeypatch):
    # patch the ceiling tiny so a 200x200 image counts as "large" without
    # allocating a real multi-megapixel test image
    monkeypatch.setattr(f, "WORK_CAP", 10_000)
    with open_guarded(_bytes(200, 200, "JPEG")) as img:
        img.load()
        assert img.width < 200 and img.height < 200  # libjpeg DCT-scaled during decode
        assert img.width * img.height < 200 * 200


def test_large_non_jpeg_is_rejected(monkeypatch):
    # other formats can't be partially decoded -> still rejected above WORK_CAP
    monkeypatch.setattr(f, "WORK_CAP", 10_000)
    with pytest.raises(ValueError):
        open_guarded(_bytes(200, 200, "PNG"))


def test_above_hard_cap_is_rejected(monkeypatch):
    # beyond the absolute ceiling, every format is rejected (true bomb guard)
    monkeypatch.setattr(f, "HARD_CAP", 10_000)
    with pytest.raises(ValueError):
        open_guarded(_bytes(200, 200, "JPEG"))
