"""Open-vocabulary voter using a SigLIP 2 image-text model.

Default model: google/siglip2-base-patch16-224  (Apache-2.0).
https://huggingface.co/google/siglip2-base-patch16-224

The iNat (14 taxa) and timm (~8 ImageNet classes) voters are *closed-vocabulary*
classifiers: an arachnid with no matching class gets little or no positive
evidence. This voter instead scores the image against free-text prompts, so it
recognises arachnids the other two have no class for (huntsman, jumping, camel
spiders, most harvestmen, ...) and adds independent positive evidence on exactly
the borderline images the closed-vocab voters see only weakly.

SigLIP uses a sigmoid (not softmax) head, so every prompt yields an *independent*
calibrated probability in [0, 1] -- no competing "background" prompt set needed.
This voter takes the strongest block-prompt probability as positive evidence:

    evidence = gain * max_p( sigmoid( logit_scale * <img, text_p> + logit_bias ) )

It contributes positive evidence only (it never argues against a block), like
the iNat voter.

Off by default. Enable with IMGEDGE_SIGLIP=1 and install the deps:
    pip install -e ".[voters,siglip]"        # needs torch (voters) + transformers

Env overrides:
    IMGEDGE_SIGLIP            1 to enable the voter (read by the server; default 0)
    IMGEDGE_SIGLIP_MODEL      HF model id (default: google/siglip2-base-patch16-224)
    IMGEDGE_SIGLIP_PROMPTS    comma-separated block prompts (default: the set below)
    IMGEDGE_SIGLIP_WEIGHT     evidence weight in the ensemble (default: 0.5)
    IMGEDGE_SIGLIP_THRESHOLD  the voter's own discrete-vote threshold (default: 0.5)
    IMGEDGE_SIGLIP_GAIN       scale raw sigmoid prob -> evidence (default: 1.0)

NOTE: SigLIP's sigmoid probabilities are calibrated for retrieval and can read
low in absolute terms even on true matches. Tune IMGEDGE_SIGLIP_GAIN /
IMGEDGE_SIGLIP_WEIGHT against the evaluation harness before trusting the defaults.
"""

import os
import threading

import numpy as np

from imgedge.voters.base import Voter

DEFAULT_MODEL = os.environ.get("IMGEDGE_SIGLIP_MODEL", "google/siglip2-base-patch16-224")
WEIGHT = float(os.environ.get("IMGEDGE_SIGLIP_WEIGHT", "0.5"))
GAIN = float(os.environ.get("IMGEDGE_SIGLIP_GAIN", "1.0"))

# Open-vocabulary block prompts. SigLIP was trained on lowercase descriptive
# captions, so short noun phrases work well. The sigmoid head scores each prompt
# independently, so extra prompts only widen coverage -- they never compete.
BLOCK_PROMPTS = [
    "a photo of a spider",
    "a close-up photo of a spider",
    "a tarantula",
    "a wolf spider",
    "a jumping spider",
    "a huntsman spider",
    "a scorpion",
    "a tick",
    "a harvestman, also called a daddy longlegs",
    "a spider in its web",
]


def _block_prob(logits, gain):
    """Pure scoring: sigmoid(logits) per prompt, take the max, scale by gain.

    `logits` is a 1-D array of per-prompt SigLIP logits
    (logit_scale * <img, text> + logit_bias). Returns
    (evidence, per_prompt_probs) with evidence clamped to [0, 1].
    """
    arr = np.asarray(logits, dtype=np.float64).ravel()
    probs = 1.0 / (1.0 + np.exp(-arr))
    top = float(probs.max()) if probs.size else 0.0
    return max(0.0, min(1.0, gain * top)), probs


def _split_env(name):
    raw = os.environ.get(name, "")
    return [t.strip() for t in raw.split(",") if t.strip()] if raw.strip() else None


class SiglipVoter(Voter):
    def __init__(self, model_name=DEFAULT_MODEL, threshold=0.5, weight=WEIGHT, prompts=None, gain=GAIN):
        super().__init__(threshold, weight)
        # Heavy deps are imported lazily so the module (and its pure scoring
        # helpers) import cleanly without torch/transformers installed.
        import torch  # type: ignore
        from transformers import AutoModel, AutoProcessor  # type: ignore

        self._torch = torch
        self.name = f"siglip:{model_name.split('/')[-1]}"
        self.gain = float(gain)
        self.prompts = list(prompts or _split_env("IMGEDGE_SIGLIP_PROMPTS") or BLOCK_PROMPTS)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = AutoModel.from_pretrained(model_name).eval().to(self.device)
        self.processor = AutoProcessor.from_pretrained(model_name)
        self._lock = threading.Lock()
        self.backend = "siglip"
        self.provider = f"transformers/{self.device}"

        # Precompute the normalised text embeddings once; SigLIP needs the text
        # padded to a fixed length (max_length=64).
        text = self.processor(text=self.prompts, padding="max_length", max_length=64, return_tensors="pt")
        text = text.to(self.device)
        with torch.inference_mode():
            temb = self.model.get_text_features(**text)
            self._text_emb = torch.nn.functional.normalize(temb, dim=-1)
        self._logit_scale = self.model.logit_scale.exp().detach()
        self._logit_bias = self.model.logit_bias.detach()

    def assess(self, img):
        torch = self._torch
        inputs = self.processor(images=img.convert("RGB"), return_tensors="pt").to(self.device)
        with self._lock, torch.inference_mode():
            iemb = self.model.get_image_features(**inputs)
            iemb = torch.nn.functional.normalize(iemb, dim=-1)
            logits = (iemb @ self._text_emb.t()) * self._logit_scale + self._logit_bias
            logits = logits[0].float().cpu().numpy()
        evidence, probs = _block_prob(logits, self.gain)
        details = {
            "block_p": round(evidence, 5),
            "prompts": {p: round(float(q), 5) for p, q in zip(self.prompts, probs, strict=True)},
        }
        return evidence, evidence, details  # positive-only evidence (score == evidence)

    def score(self, img):
        return self.assess(img)[0]
