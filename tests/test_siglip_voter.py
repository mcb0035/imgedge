"""SigLIP voter scoring math (pure helpers) + an opt-in model-path smoke test."""

import os

import numpy as np
import pytest

from imgedge.voters.siglip_voter import ATYPICAL_PROMPTS, BLOCK_PROMPTS, CORE_PROMPTS, _block_prob, _pooled, _split_env


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


def test_core_is_the_tight_siglip_default():
    # SigLIP defaults to CORE (tight); the looser atypical prompts moved to
    # MobileCLIP because they lifted SigLIP's web false-positive rate.
    assert BLOCK_PROMPTS == CORE_PROMPTS + ATYPICAL_PROMPTS
    assert set(CORE_PROMPTS).isdisjoint(ATYPICAL_PROMPTS)
    core = " ".join(CORE_PROMPTS).lower()
    assert "spider" in core and "scorpion" in core
    assert "microscope" not in core and "egg sac" not in core  # atypical excluded


def test_split_env_parses_and_trims(monkeypatch):
    monkeypatch.setenv("IMGEDGE_SIGLIP_PROMPTS", " a spider , a scorpion ,, ")
    assert _split_env("IMGEDGE_SIGLIP_PROMPTS") == ["a spider", "a scorpion"]
    monkeypatch.delenv("IMGEDGE_SIGLIP_PROMPTS")
    assert _split_env("IMGEDGE_SIGLIP_PROMPTS") is None


def test_pooled_extracts_pooler_output():
    # transformers 5.x get_*_features returns a ModelOutput, not a tensor
    class _Out:
        pooler_output = "EMB"

    assert _pooled(_Out()) == "EMB"
    assert _pooled("TENSOR") == "TENSOR"  # older API: tensor passthrough

    class _NoPool:
        pooler_output = None

    obj = _NoPool()
    assert _pooled(obj) is obj  # None pooler -> return the object unchanged


@pytest.mark.skipif(
    os.environ.get("IMGEDGE_TEST_SIGLIP") != "1",
    reason="set IMGEDGE_TEST_SIGLIP=1 to run the SigLIP model-path test (loads ~1GB model)",
)
def test_model_path_scores_synthetic_image():
    # Guards the real inference path -- the transformers 5.x get_*_features change
    # slipped past the pure-helper tests. Runs only when explicitly opted in.
    from PIL import Image

    from imgedge.voters.siglip_voter import SiglipVoter

    v = SiglipVoter()
    score, evidence, details = v.assess(Image.new("RGB", (128, 128), (128, 128, 128)))
    assert 0.0 <= score <= 1.0
    assert score == evidence  # positive-only voter
    assert set(details) == {"block_p", "prompts"}
    assert len(details["prompts"]) == len(v.prompts)
