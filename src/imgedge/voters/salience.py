"""Image-salience weighting for the voting ensemble.

A big, sharp, photorealistic close-up of an arachnid is both the most certain
detection and the most disruptive to see, so it should be blocked aggressively.
A tiny, low-detail, stylised, or "fleeting" image (a thumbnail, a video poster,
a decorative CSS background, a cartoon) is weaker evidence and should be allowed
to slip through more easily.

`image_salience(img, meta)` returns a multiplier applied to the *positive* block
evidence:

  > 1.0  amplify   (large / detailed / photographic / foreground <img>)
  < 1.0  attenuate (small / flat / stylised / poster / background)

It uses only the decoded pixels (PIL + numpy) plus optional page hints (rendered
size and element kind), so it adds no model dependencies. "Magnified vs distant"
is handled implicitly: a magnified close-up is large and detailed (high here)
and a distant subject leaves the classifier itself unsure (low arachnid prob).
"""

import math

import numpy as np

# Multiplier band. Salience only scales the magnitude of positive evidence; it
# never flips the sign, so a look-alike's negative evidence is always honoured.
S_MIN = 0.35
S_MAX = 1.30

# How "fleeting"/decorative each surface is. A foreground <img> is full weight;
# video posters and CSS backgrounds are transient/secondary -> down-weighted.
KIND_FACTOR = {
    "img": 1.0,
    "input": 1.0,
    "svg": 0.75,  # inline SVG: usually icons / line art
    "poster": 0.6,  # video frame: fleeting
    "bg": 0.65,  # CSS background: decorative / distant
}


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def _size_factor(dim):
    """Linear size (px) -> [0.5 .. 1.15]. Bigger image = higher block chance."""
    if dim <= 48:
        return 0.5
    if dim <= 256:
        return 0.5 + (dim - 48) / 208.0 * 0.5  # 48px->0.5, 256px->1.0
    return 1.0 + _clamp((dim - 256) / 384.0, 0.0, 1.0) * 0.15  # 640px+ -> 1.15


def _photoreal_factor(img):
    """Photo-vs-illustration from colour richness + local detail -> [0.5 .. 1.15].

    Photographs have many distinct colours and dense micro-variation; flat logos,
    cartoons and line art have small palettes and large uniform regions, so a
    stylised drawing of a spider is weighted well below a real photo of one.
    """
    small = img.convert("RGB").resize((128, 128))
    a = np.asarray(small, dtype=np.uint8) >> 3  # 5 bits/channel (0..31)
    codes = (a[..., 0].astype(np.uint32) << 10) | (a[..., 1].astype(np.uint32) << 5) | a[..., 2].astype(np.uint32)
    richness = min(np.unique(codes).size / 2000.0, 1.0)  # ~2000+ colours -> rich
    dx = (a[:, 1:, :] != a[:, :-1, :]).any(-1).mean()
    dy = (a[1:, :, :] != a[:-1, :, :]).any(-1).mean()
    detail = float(0.5 * (dx + dy))  # photos high, flat art low
    photographic = 0.6 * richness + 0.4 * detail  # [0..1]
    return _clamp(0.55 + 0.6 * photographic, 0.5, 1.15)


def image_salience(img, meta=None):
    """Return (multiplier, breakdown) scaling the positive block evidence."""
    meta = meta or {}
    kind = meta.get("kind") or "img"

    # "Larger" = the rendered display size the page reported, else the decoded
    # pixel size. Use the geometric mean so a thin banner isn't treated as huge.
    w = meta.get("w") or 0
    h = meta.get("h") or 0
    if not (w > 0 and h > 0):
        w, h = img.width, img.height
    dim = math.sqrt(max(1.0, float(w) * float(h)))

    size = _size_factor(dim)
    media = KIND_FACTOR.get(kind, 1.0)
    photo = _photoreal_factor(img)

    s = _clamp(size * media * photo, S_MIN, S_MAX)
    return s, {
        "size": round(size, 3),
        "media": round(media, 3),
        "photo": round(photo, 3),
        "salience": round(s, 3),
    }
