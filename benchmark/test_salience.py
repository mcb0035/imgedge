# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Salience-weighting benchmarks (``voters/salience.image_salience``).

Salience runs once per classified image and is pure numpy/Pillow: a 128x128
resize plus colour-richness and local-detail statistics. It is CPU-bound and on
the request path, so it is worth tracking.
"""

import pytest
from _assets import make_image

from imgedge.voters.salience import image_salience


@pytest.mark.parametrize("side", [128, 400, 1024], ids=["128", "400", "1024"])
def test_image_salience(benchmark, side):
    img = make_image(side, seed=1)
    meta = {"kind": "img", "w": side, "h": side}
    mult, _ = benchmark(image_salience, img, meta)
    assert mult > 0
