"""SigLIP voter scoring math (pure helpers; no model download)."""

import numpy as np

from imgedge.voters.siglip_voter import BLOCK_PROMPTS, _block_prob, _split_env


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def test_block_prob_takes_max_sigmoid():
    ev, probs = _block_prob([-10.0, 2.0, -3.0], gain=1.0)
    assert probs.shape == (3,)
    assert abs(ev - _sigmoid(2.0)) < 1e-9  # strongest prompt wins


def test_block_prob_gain_scales_and_clamps():
    # sigmoid(0) = 0.5; gain 3 -> 1.5 -> clamped to 1.0
    ev, _ = _block_prob([0.0], gain=3.0)
    assert ev == 1.0
    # a strongly negative logit yields ~0 evidence
    ev2, _ = _block_prob([-100.0], gain=1.0)
    assert ev2 < 1e-6


def test_block_prob_empty_is_zero():
    ev, probs = _block_prob([], gain=1.0)
    assert ev == 0.0
    assert probs.size == 0


def test_block_prompts_are_arachnid_specific():
    # guard against re-introducing a generic prompt that would over-fire
    assert BLOCK_PROMPTS
    joined = " ".join(BLOCK_PROMPTS).lower()
    assert "spider" in joined and "scorpion" in joined
    assert "monkey" not in joined  # "spider monkey" is not an arachnid


def test_split_env_parses_and_trims(monkeypatch):
    monkeypatch.setenv("IMGEDGE_SIGLIP_PROMPTS", " a spider , a scorpion ,, ")
    assert _split_env("IMGEDGE_SIGLIP_PROMPTS") == ["a spider", "a scorpion"]
    monkeypatch.delenv("IMGEDGE_SIGLIP_PROMPTS")
    assert _split_env("IMGEDGE_SIGLIP_PROMPTS") is None
