"""The iNat-confidence override: a confident real-organism match blocks outright
and is not vetoed by the look-alike contrast voter's negative evidence.
"""

from imgedge.voters.base import VoteEnsemble, Voter


class _Stub(Voter):
    def __init__(self, name, score, evidence, weight=1.0):
        super().__init__(threshold=0.5, weight=weight)
        self.name = name
        self._s = float(score)
        self._e = float(evidence)

    def assess(self, img):
        return self._s, self._e


def _ensemble(inat_score, contrast_evidence, inat_override):
    inat = _Stub("inat", inat_score, inat_score)
    contrast = _Stub("timm", 0.0, contrast_evidence)
    ens = VoteEnsemble([inat, contrast], policy="evidence", threshold=0.5, inat_override=inat_override)
    ens.inat = inat
    return ens


def test_confident_inat_overrides_contrast_veto():
    # Without the override: combined = clamp(0.95 - 0.9) = 0.05 -> would NOT block.
    ens = _ensemble(inat_score=0.95, contrast_evidence=-0.9, inat_override=0.9)
    v = ens.classify(None, None)
    assert v["block"] is True
    assert v["dbg"]["override"] is True
    assert v["score"] == 0.95  # score pinned to iNat's own confidence


def test_no_override_below_threshold():
    ens = _ensemble(inat_score=0.7, contrast_evidence=-0.9, inat_override=0.9)
    v = ens.classify(None, None)
    assert v["block"] is False
    assert v["dbg"]["override"] is False


def test_override_disabled_when_above_one():
    ens = _ensemble(inat_score=0.95, contrast_evidence=-0.9, inat_override=1.1)
    v = ens.classify(None, None)
    assert v["block"] is False
    assert v["dbg"]["override"] is False
