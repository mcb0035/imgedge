"""Per-request threshold + salience overrides on the voting ensemble."""

from PIL import Image

from imgedge.voters.base import VoteEnsemble, Voter


class _Fixed(Voter):
    """A voter that always emits a fixed signed evidence (one forward, no model)."""

    name = "fixed"

    def __init__(self, evidence):
        super().__init__()
        self._ev = evidence

    def assess(self, img):
        return max(0.0, self._ev), self._ev


def _img(w=64, h=64):
    return Image.new("RGB", (w, h), (120, 60, 30))


def _verdict(evidence, *, threshold=None, salience=None, meta=None, img=None):
    ens = VoteEnsemble([_Fixed(evidence)], policy="evidence", threshold=0.5)
    return ens.classify(img if img is not None else _img(),
                        meta=meta, threshold=threshold, salience=salience)


def test_threshold_override_changes_block():
    # salience=0 removes size/detail weighting -> combined == evidence (0.4)
    assert _verdict(0.4, salience=0.0)["block"] is False           # 0.4 < 0.5 default
    assert _verdict(0.4, threshold=0.3, salience=0.0)["block"] is True  # 0.4 >= 0.3


def test_block_is_monotonic_in_threshold():
    # A block at a given threshold must stay blocked at every lower threshold.
    assert _verdict(0.5, threshold=0.5, salience=0.0)["block"] is True
    for lower in (0.45, 0.3, 0.1):
        assert _verdict(0.5, threshold=lower, salience=0.0)["block"] is True


def test_salience_strength_zero_disables_weighting():
    # A tiny flat CSS-background image is normally suppressed below threshold;
    # salience=0 turns the weighting off so the same evidence blocks.
    meta = {"kind": "bg"}
    small = _img(30, 30)
    assert _verdict(0.6, salience=1.0, meta=meta, img=small)["block"] is False
    assert _verdict(0.6, salience=0.0, meta=meta, img=small)["block"] is True
