"""Ensemble-voting and pre/post-processing benchmarks.

``VoteEnsemble.classify`` combines the voters' signed evidence and (under the
default "evidence" policy) scales it by image salience -- the verdict logic run
for every request. The model pre/post-processing helpers (``prep_input`` and
``postprocess``) are the numpy reshaping/normalisation steps around inference.
"""

import numpy as np
import pytest
from _assets import make_image

from imgedge.inat.inat_filter import postprocess, prep_input
from imgedge.voters.base import VoteEnsemble, Voter


class _FixedVoter(Voter):
    """A voter returning a fixed (score, signed-evidence) without any model."""

    def __init__(self, name, evidence, **kw):
        super().__init__(**kw)
        self.name = name
        self._ev = evidence

    def assess(self, img):
        return max(0.0, min(1.0, abs(self._ev))), self._ev


def test_ensemble_classify_evidence(benchmark):
    """Evidence-policy verdict over a 3-voter ensemble, including the salience
    weighting on a real decoded image."""
    img = make_image(400, seed=2)
    ensemble = VoteEnsemble(
        [
            _FixedVoter("inat", 0.6, weight=1.0),
            _FixedVoter("timm", 0.4, weight=0.5),
            _FixedVoter("lookalike", -0.3, weight=0.5),
        ],
        policy="evidence",
        threshold=0.5,
    )
    verdict = benchmark(ensemble.classify, img, {"kind": "img", "w": 400, "h": 400})
    assert "block" in verdict


@pytest.mark.parametrize("side", [299, 768], ids=["299", "768"])
def test_prep_input(benchmark, side):
    """Resize-to-model-input + NHWC batch build for a float model."""
    img = make_image(side, seed=3)
    batch = benchmark(prep_input, img, 299, 299, False)
    assert batch.shape == (1, 299, 299, 3)


def test_postprocess(benchmark):
    """Normalise a 10k-class logit vector and sum the masked probability mass."""
    rng = np.random.default_rng(4)
    out = rng.random(10000).astype("float32")
    mask = np.zeros(10000, dtype=bool)
    mask[::7] = True
    score = benchmark(postprocess, out, mask)
    assert 0.0 <= score <= 1.0
