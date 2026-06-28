"""Ensemble voting + salience interaction (voters/base.py)."""

from imgedge.voters import base
from imgedge.voters.base import VoteEnsemble, Voter


class _Stub(Voter):
    """A voter returning a fixed (clamped score, signed evidence)."""

    def __init__(self, evidence, name="stub", **kw):
        super().__init__(**kw)
        self.name = name
        self._ev = evidence

    def assess(self, img):
        return max(0.0, min(1.0, self._ev)), self._ev


def _pin_salience(monkeypatch, value=1.0):
    monkeypatch.setattr(base, "image_salience", lambda img, meta=None: (value, {"salience": value}))


def test_evidence_increase_on_real_arachnid(monkeypatch):
    _pin_salience(monkeypatch)
    inat = _Stub(0.45, "inat", weight=1.0)   # alone: below threshold
    timm = _Stub(0.90, "timm", weight=0.5)   # confident arachnid -> pushes over
    ens = VoteEnsemble([inat, timm], policy="evidence", threshold=0.5)
    v = ens.classify(None)
    assert v["block"] is True                 # 0.45 + 0.5*0.90 = 0.90
    assert v["score"] == 0.9


def test_evidence_decrease_on_lookalike(monkeypatch):
    _pin_salience(monkeypatch)
    inat = _Stub(0.60, "inat", weight=1.0)   # alone: would block
    timm = _Stub(-0.90, "timm", weight=0.5)  # look-alike -> argues against
    ens = VoteEnsemble([inat, timm], policy="evidence", threshold=0.5)
    assert ens.classify(None)["block"] is False   # 0.60 - 0.45 = 0.15


def test_salience_scales_only_positive(monkeypatch):
    _pin_salience(monkeypatch, 0.5)
    inat = _Stub(0.80, "inat", weight=1.0)
    ens = VoteEnsemble([inat], policy="evidence", threshold=0.5)
    assert ens.classify(None)["block"] is False   # 0.80 * 0.5 = 0.40


def test_policy_any_blocks_on_one():
    ens = VoteEnsemble(
        [_Stub(0.6, "a", threshold=0.5), _Stub(0.1, "b", threshold=0.5)], policy="any"
    )
    assert ens.classify(None)["block"] is True


def test_policy_all_needs_every_voter():
    ens = VoteEnsemble(
        [_Stub(0.6, "a", threshold=0.5), _Stub(0.1, "b", threshold=0.5)], policy="all"
    )
    assert ens.classify(None)["block"] is False


def test_broken_voter_abstains(monkeypatch):
    _pin_salience(monkeypatch)

    class _Boom(Voter):
        name = "boom"

        def assess(self, img):
            raise RuntimeError("boom")

    ens = VoteEnsemble([_Stub(0.9, "good", weight=1.0), _Boom()], policy="evidence", threshold=0.5)
    assert ens.classify(None)["block"] is True   # broken voter -> (0, 0), never raises
