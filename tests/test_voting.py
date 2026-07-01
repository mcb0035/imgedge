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
    inat = _Stub(0.45, "inat", weight=1.0)  # alone: below threshold
    timm = _Stub(0.90, "timm", weight=0.5)  # confident arachnid -> pushes over
    ens = VoteEnsemble([inat, timm], policy="evidence", threshold=0.5)
    v = ens.classify(None)
    assert v["block"] is True  # 0.45 + 0.5*0.90 = 0.90
    assert v["score"] == 0.9


def test_evidence_decrease_on_lookalike(monkeypatch):
    _pin_salience(monkeypatch)
    inat = _Stub(0.60, "inat", weight=1.0)  # alone: would block
    timm = _Stub(-0.90, "timm", weight=0.5)  # look-alike -> argues against
    ens = VoteEnsemble([inat, timm], policy="evidence", threshold=0.5)
    assert ens.classify(None)["block"] is False  # 0.60 - 0.45 = 0.15


def test_salience_is_boost_only(monkeypatch):
    # A raw multiplier < 1 is clamped to 1.0 -- salience never suppresses.
    _pin_salience(monkeypatch, 0.5)
    inat = _Stub(0.80, "inat", weight=1.0)
    ens = VoteEnsemble([inat], policy="evidence", threshold=0.5)
    assert ens.classify(None)["block"] is True  # clamped to 1.0 -> 0.80 (not 0.40)

    # A raw multiplier > 1 amplifies the positive evidence.
    _pin_salience(monkeypatch, 1.5)
    weak = VoteEnsemble([_Stub(0.40, "inat", weight=1.0)], policy="evidence", threshold=0.5)
    assert weak.classify(None)["block"] is True  # 0.40 * 1.5 = 0.60


def test_policy_any_blocks_on_one():
    ens = VoteEnsemble([_Stub(0.6, "a", threshold=0.5), _Stub(0.1, "b", threshold=0.5)], policy="any")
    assert ens.classify(None)["block"] is True


def test_policy_all_needs_every_voter():
    ens = VoteEnsemble([_Stub(0.6, "a", threshold=0.5), _Stub(0.1, "b", threshold=0.5)], policy="all")
    assert ens.classify(None)["block"] is False


def test_broken_voter_abstains(monkeypatch):
    _pin_salience(monkeypatch)

    class _Boom(Voter):
        name = "boom"

        def assess(self, img):
            raise RuntimeError("boom")

    ens = VoteEnsemble([_Stub(0.9, "good", weight=1.0), _Boom()], policy="evidence", threshold=0.5)
    assert ens.classify(None)["block"] is True  # broken voter -> (0, 0), never raises


def _deferred(stub):
    stub.deferred = True
    return stub


def test_cascade_skips_deferred_below_gate(monkeypatch):
    _pin_salience(monkeypatch)  # mult forced to 1.0
    cheap = _Stub(0.04, "cheap", weight=1.0)  # below the gate floor
    expensive = _deferred(_Stub(0.90, "siglip", weight=1.0))
    ens = VoteEnsemble([cheap, expensive], policy="evidence", threshold=0.18, gate=0.05)
    v = ens.classify(None)
    assert v["block"] is False  # 0.04 < gate -> deferred never runs
    assert v["votes"]["siglip"] == 0.0  # skipped


def test_cascade_runs_deferred_in_band(monkeypatch):
    _pin_salience(monkeypatch)
    cheap = _Stub(0.10, "cheap", weight=1.0)  # gate <= 0.10 < threshold
    expensive = _deferred(_Stub(0.90, "siglip", weight=1.0))
    ens = VoteEnsemble([cheap, expensive], policy="evidence", threshold=0.18, gate=0.05)
    v = ens.classify(None)
    assert v["block"] is True  # 0.10 + 0.90 over threshold
    assert v["votes"]["siglip"] == 0.9  # deferred ran


def test_cascade_skips_deferred_when_cheap_already_blocks(monkeypatch):
    _pin_salience(monkeypatch)
    cheap = _Stub(0.50, "cheap", weight=1.0)  # already >= threshold
    expensive = _deferred(_Stub(0.90, "siglip", weight=1.0))
    ens = VoteEnsemble([cheap, expensive], policy="evidence", threshold=0.18, gate=0.05)
    v = ens.classify(None)
    assert v["block"] is True  # cheap voter alone blocks
    assert v["votes"]["siglip"] == 0.0  # deferred not needed -> skipped


def test_only_restricts_to_a_voter_subset(monkeypatch):
    _pin_salience(monkeypatch)
    inat = _Stub(0.10, "inat", weight=1.0)
    timm = _Stub(0.05, "timm", weight=0.5)
    siglip = _deferred(_Stub(0.90, "siglip", weight=2.0))
    ens = VoteEnsemble([inat, timm, siglip], policy="evidence", threshold=0.18, gate=0.0)

    # Full run: the deferred voter is in-band (cheap 0.125 < 0.18) and blocks.
    full = ens.classify(None)
    assert full["block"] is True
    assert set(full["votes"]) == {"inat", "timm", "siglip"}

    # only={inat,timm}: siglip is excluded entirely (not merely skipped at 0.0).
    sub = ens.classify(None, only={"inat", "timm"})
    assert sub["block"] is False  # 0.10 + 0.5*0.05 = 0.125 < 0.18
    assert set(sub["votes"]) == {"inat", "timm"}


def test_only_none_runs_every_voter(monkeypatch):
    _pin_salience(monkeypatch)
    ens = VoteEnsemble([_Stub(0.9, "inat", weight=1.0)], policy="evidence", threshold=0.5)
    assert set(ens.classify(None, only=None)["votes"]) == {"inat"}
