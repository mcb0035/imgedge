"""Image-salience weighting (voters/salience.py)."""

import numpy as np
from PIL import Image

from salience import S_MAX, S_MIN, image_salience


def _noise(seed, size):
    rng = np.random.default_rng(seed)
    return Image.fromarray((rng.random((size, size, 3)) * 255).astype("uint8"))


def test_multiplier_within_bounds():
    img = Image.new("RGB", (200, 200), (123, 50, 200))
    s, info = image_salience(img, {"kind": "img", "w": 200, "h": 200})
    assert S_MIN <= s <= S_MAX
    assert {"size", "media", "photo", "salience"} <= set(info)


def test_large_photo_outweighs_tiny_drawing():
    photo = _noise(0, 400)
    drawing = Image.new("RGB", (40, 40), (200, 30, 30))
    big = image_salience(photo, {"kind": "img", "w": 600, "h": 600})[0]
    small = image_salience(drawing, {"kind": "img", "w": 40, "h": 40})[0]
    assert big > small


def test_fleeting_surfaces_downweighted():
    photo = _noise(1, 400)
    as_img = image_salience(photo, {"kind": "img", "w": 600, "h": 600})[0]
    as_poster = image_salience(photo, {"kind": "poster", "w": 600, "h": 600})[0]
    assert as_poster < as_img


def test_missing_meta_falls_back_to_decoded_size():
    photo = _noise(2, 300)
    s, _ = image_salience(photo, None)  # no rendered size -> use decoded dims
    assert S_MIN <= s <= S_MAX
