"""Open-vocabulary voter using a MobileCLIP model (open_clip).

Default: MobileCLIP2-S0 / dfndr2b -- a small, fast CLIP variant built for
on-device inference. It plays the same role as the SigLIP voter (scoring the
image against free-text arachnid prompts) but is far cheaper on CPU, so it is
the better choice when latency matters more than the last point of recall.

CLIP is contrastive (not SigLIP's sigmoid), so this voter uses the cosine
similarity between the image and each block prompt directly, takes the strongest,
and scales it into positive-only evidence:

    evidence = clamp(gain * (max_cos - offset), 0, 1)

Like SigLIP it is `deferred` (the ensemble cascade decides when to run it) and
contributes positive evidence only. The block prompts are shared with the SigLIP
voter (imgedge.voters.siglip_voter.BLOCK_PROMPTS).

Off by default. Enable with IMGEDGE_MOBILECLIP=1 and install the deps:
    pip install -e ".[voters,mobileclip]"

Env overrides:
    IMGEDGE_MOBILECLIP            1 to enable the voter (read by the server; default 0)
    IMGEDGE_MOBILECLIP_MODEL      open_clip model name (default: MobileCLIP2-S0)
    IMGEDGE_MOBILECLIP_PRETRAINED open_clip pretrained tag (default: dfndr2b)
    IMGEDGE_MOBILECLIP_PROMPTS    comma-separated block prompts (default: the shared set)
    IMGEDGE_MOBILECLIP_WEIGHT     evidence weight in the ensemble (default: 1.0)
    IMGEDGE_MOBILECLIP_THRESHOLD  the voter's own discrete-vote threshold (default: 0.5)
    IMGEDGE_MOBILECLIP_GAIN       scale (max_cos - offset) -> evidence (default: 2.0)
    IMGEDGE_MOBILECLIP_OFFSET     cosine baseline subtracted before the gain (default: 0.15)

NOTE: gain / offset / weight are starting points -- calibrate them against the
evaluation harness (as for SigLIP) before relying on the defaults.
"""

import os
import threading

import numpy as np

from imgedge.voters.base import Voter
from imgedge.voters.siglip_voter import BLOCK_PROMPTS, _split_env

DEFAULT_MODEL = os.environ.get("IMGEDGE_MOBILECLIP_MODEL", "MobileCLIP2-S0")
DEFAULT_PRETRAINED = os.environ.get("IMGEDGE_MOBILECLIP_PRETRAINED", "dfndr2b")
GAIN = float(os.environ.get("IMGEDGE_MOBILECLIP_GAIN", "2.0"))
OFFSET = float(os.environ.get("IMGEDGE_MOBILECLIP_OFFSET", "0.15"))


def _cos_evidence(cos, gain, offset):
    """Strongest image-prompt cosine similarity -> positive-only evidence [0, 1].

    `cos` is a 1-D array of per-prompt cosine similarities. Returns
    (evidence, similarities).
    """
    arr = np.asarray(cos, dtype=np.float64).ravel()
    top = float(arr.max()) if arr.size else 0.0
    return max(0.0, min(1.0, gain * (top - offset))), arr


class MobileClipVoter(Voter):
    deferred = True  # the ensemble cascade decides when to run it (like SigLIP)

    def __init__(
        self,
        model_name=DEFAULT_MODEL,
        pretrained=DEFAULT_PRETRAINED,
        threshold=0.5,
        weight=1.0,
        prompts=None,
        gain=GAIN,
        offset=OFFSET,
    ):
        super().__init__(threshold, weight)
        # Heavy deps imported lazily so the module (and its pure scoring helper)
        # import cleanly without torch/open_clip installed.
        import open_clip  # type: ignore
        import torch  # type: ignore

        self._torch = torch
        self.name = f"mobileclip:{model_name}"
        self.gain = float(gain)
        self.offset = float(offset)
        self.prompts = list(prompts or _split_env("IMGEDGE_MOBILECLIP_PROMPTS") or BLOCK_PROMPTS)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
        self.model.eval().to(self.device)
        self.tokenizer = open_clip.get_tokenizer(model_name)
        self._lock = threading.Lock()
        self.backend = "open_clip"
        self.provider = f"open_clip/{self.device}"

        # Precompute the normalised text embeddings once.
        tokens = self.tokenizer(self.prompts).to(self.device)
        with torch.no_grad():
            temb = self.model.encode_text(tokens)
            self._text_emb = torch.nn.functional.normalize(temb, dim=-1)

    def assess(self, img):
        torch = self._torch
        tensor = self.preprocess(img.convert("RGB")).unsqueeze(0).to(self.device)
        with self._lock, torch.no_grad():
            iemb = self.model.encode_image(tensor)
            iemb = torch.nn.functional.normalize(iemb, dim=-1)
            cos = (iemb @ self._text_emb.t())[0].float().cpu().numpy()
        evidence, sims = _cos_evidence(cos, self.gain, self.offset)
        details = {
            "block_p": round(evidence, 5),
            "prompts": {p: round(float(c), 5) for p, c in zip(self.prompts, sims, strict=True)},
        }
        return evidence, evidence, details  # positive-only evidence (score == evidence)

    def score(self, img):
        return self.assess(img)[0]
