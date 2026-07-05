# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Shared synthetic-image fixtures for the benchmark suite.

Images are generated deterministically (seeded RNG) so the encoded bytes and the
decoded pixels are identical from run to run -- a prerequisite for stable,
comparable CodSpeed measurements.
"""

import io

import numpy as np
from PIL import Image


def make_image(side, seed=0):
    """A deterministic RGB noise image of ``side``x``side`` (seeded, so encoded
    bytes and decoded pixels are identical run to run)."""
    rng = np.random.default_rng(seed)
    arr = (rng.random((side, side, 3)) * 255).astype("uint8")
    return Image.fromarray(arr)


def encode(side, fmt="JPEG", seed=0, **save_kwargs):
    """Return the encoded bytes for a deterministic ``side``x``side`` image."""
    buf = io.BytesIO()
    make_image(side, seed).save(buf, fmt, **save_kwargs)
    return buf.getvalue()
