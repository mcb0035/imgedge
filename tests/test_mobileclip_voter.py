"""MobileCLIP voter scoring math (pure helper) + an opt-in model-path test."""

import os

import pytest

from imgedge.voters.mobileclip_voter import _cos_evidence


def test_cos_evidence_takes_max_minus_offset():
    ev, sims = _cos_evidence([0.05, 0.30, 0.10], gain=2.0, offset=0.1)
    assert sims.shape == (3,)
    assert abs(ev - 2.0 * (0.30 - 0.1)) < 1e-9  # strongest prompt, baseline-subtracted


def test_cos_evidence_clamps():
    assert _cos_evidence([0.9], gain=2.0, offset=0.1)[0] == 1.0  # 2*(0.9-0.1)=1.6 -> clamp 1.0
    assert _cos_evidence([0.05], gain=2.0, offset=0.1)[0] == 0.0  # below the offset -> 0


def test_cos_evidence_empty():
    ev, sims = _cos_evidence([], gain=2.0, offset=0.1)
    assert ev == 0.0
    assert sims.size == 0


def test_mobileclip_carries_full_set_siglip_defaults_to_core():
    from imgedge.voters.mobileclip_voter import BLOCK_PROMPTS
    from imgedge.voters.siglip_voter import ATYPICAL_PROMPTS, CORE_PROMPTS
    from imgedge.voters.siglip_voter import BLOCK_PROMPTS as SIG_FULL

    # MobileCLIP defaults to the full shared set; SigLIP defaults to the tighter
    # core (the atypical prompts moved to MobileCLIP-only to cut SigLIP web FPs).
    assert BLOCK_PROMPTS is SIG_FULL  # still the one shared full list
    assert BLOCK_PROMPTS == CORE_PROMPTS + ATYPICAL_PROMPTS
    assert set(ATYPICAL_PROMPTS).isdisjoint(CORE_PROMPTS)


@pytest.mark.skipif(
    os.environ.get("IMGEDGE_TEST_MOBILECLIP") != "1",
    reason="set IMGEDGE_TEST_MOBILECLIP=1 to run the MobileCLIP model-path test (downloads the model)",
)
def test_model_path_scores_synthetic_image():
    from PIL import Image

    from imgedge.voters.mobileclip_voter import MobileClipVoter

    v = MobileClipVoter()
    score, evidence, details = v.assess(Image.new("RGB", (128, 128), (128, 128, 128)))
    assert 0.0 <= score <= 1.0
    assert score == evidence  # positive-only voter
    assert set(details) == {"block_p", "prompts"}
    assert len(details["prompts"]) == len(v.prompts)
