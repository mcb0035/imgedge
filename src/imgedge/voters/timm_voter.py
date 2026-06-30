"""ImageNet voter using a Hugging Face / timm model.

Default model: mobilenetv3_large_100.ra_in1k  (timm, ImageNet-1k, 1000 classes).
https://huggingface.co/timm/mobilenetv3_large_100.ra_in1k

This voter contributes *signed* evidence to the ensemble:

  positive (toward block)   summed probability over BLOCK_TERMS -- the real
                            arachnid classes (tarantula, scorpion, tick, ...).
  negative (against block)  summed probability over CONTRAST_TERMS -- look-alikes
                            that are NOT arachnids: other insects/arthropods,
                            webs / geometric patterns, and drawings.

  evidence = P(arachnid) - contrast_weight * P(look-alike)

So when the second model is confident it really is an arachnid it pushes the
ensemble toward blocking; when it recognises a mere look-alike it pulls the
ensemble away. Terms are matched whole-word (case-insensitive) against the
ImageNet class descriptions, so "tick" never matches "stick".

Override the lists with env vars (comma-separated):
  IMGEDGE_TIMM_EXCLUDE   block terms       (default: the arachnid classes below)
  IMGEDGE_TIMM_CONTRAST  look-alike terms  (default: the insect/pattern set below)
  IMGEDGE_TIMM_CONTRAST_WEIGHT  how hard look-alikes argue against (default: 0.0)

Enable by installing the optional deps:  pip install -r voters/requirements.txt
The server runs fine without them; the voter is simply skipped.
"""

import os
import re
import threading

import numpy as np
import timm  # type: ignore
import torch  # type: ignore
from timm.data import create_transform, resolve_model_data_config  # type: ignore

from imgedge.voters.base import Voter

DEFAULT_MODEL = os.environ.get("IMGEDGE_TIMM_MODEL", "mobilenetv3_large_100.ra_in1k")
# Default 0.0: evaluating on real web imagery showed the look-alike contrast
# suppressed arachnid recall for almost no false-positive benefit (it mainly
# guarded against organism look-alikes, which are rare on the web). Set >0 to
# re-enable contrast subtraction.
CONTRAST_WEIGHT = float(os.environ.get("IMGEDGE_TIMM_CONTRAST_WEIGHT", "0.0"))

# Real arachnid (Arachnida) classes present in ImageNet-1k -> push toward block.
BLOCK_TERMS = [
    # specific arachnid classes -- the bare term "spider" also matches the
    # non-arachnid "spider monkey", so the real classes are listed explicitly
    "tarantula",
    "garden spider",
    "barn spider",
    "black widow",
    "wolf spider",
    "argiope",
    "scorpion",
    "tick",
    "harvestman",
    "daddy longlegs",
    "spider web",  # webs strongly co-occur with spiders -> count toward block
]

# Look-alikes that are NOT arachnids -> argue against a block. Other insects and
# arthropods, plus web / geometric-pattern / stylised-art classes. Edit freely
# or override with IMGEDGE_TIMM_CONTRAST.
CONTRAST_TERMS = [
    # other arthropods / insects commonly mistaken for spiders
    "beetle",
    "weevil",
    "ladybug",
    "ant",
    "fly",
    "bee",
    "wasp",
    "grasshopper",
    "cricket",
    "mantis",
    "cockroach",
    "walking stick",
    "stick insect",
    "cicada",
    "leafhopper",
    "lacewing",
    "dragonfly",
    "damselfly",
    "butterfly",
    "moth",
    "admiral",
    "ringlet",
    "monarch",
    "centipede",
    "millipede",
    "isopod",
    "crayfish",
    "hermit crab",
    "crab",
    "lobster",
    # webs / geometric patterns / stylised art
    "honeycomb",
    "chainlink fence",
    "window screen",
    "doily",
    "quilt",
    "maze",
    "comic book",
    "textile",
    "pattern",
    "art",
    "geometric",
]


def _split_env(name):
    raw = os.environ.get(name, "")
    return [t.strip() for t in raw.split(",") if t.strip()] if raw.strip() else None


def _patterns(terms):
    return [re.compile(r"\b" + re.escape(t.lower()) + r"\b") for t in terms]


def _mask_for(labels, terms, num_classes):
    """Boolean mask over class indices whose label whole-word-matches a term."""
    mask = np.zeros(num_classes, dtype=bool)
    if not labels or not terms:
        return mask
    pats = _patterns(terms)
    for i, lab in enumerate(labels):
        if any(p.search(lab) for p in pats):
            mask[i] = True
    return mask


def _masks_by_term(labels, terms, num_classes):
    """{term: boolean mask} for each term that matched at least one class -- used
    to report per-term probabilities for offline analysis."""
    out = {}
    if not labels or not terms:
        return out
    for t in terms:
        pat = re.compile(r"\b" + re.escape(t.lower()) + r"\b")
        mask = np.zeros(num_classes, dtype=bool)
        for i, lab in enumerate(labels):
            if pat.search(lab):
                mask[i] = True
        if mask.any():
            out[t] = mask
    return out


def _imagenet_labels(model, num_classes):
    """Best-effort ImageNet index -> human label list (lowercased), or None."""
    try:
        from timm.data import ImageNetInfo  # type: ignore

        info = ImageNetInfo()
        return [str(info.index_to_description(i, detailed=True)).lower() for i in range(num_classes)]
    except Exception:
        pass
    try:
        cfg = getattr(model, "pretrained_cfg", {}) or {}
        names = cfg.get("label_names")
        if names and len(names) == num_classes:
            return [str(n).lower() for n in names]
    except Exception:
        pass
    return None


class TimmVoter(Voter):
    def __init__(self, model_name=DEFAULT_MODEL, threshold=0.5, weight=1.0, contrast_weight=CONTRAST_WEIGHT):
        super().__init__(threshold, weight)
        self.name = f"timm:{model_name.split('.')[0]}"
        self.contrast_weight = float(contrast_weight)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = timm.create_model(model_name, pretrained=True)
        self.model.eval().to(self.device)
        cfg = resolve_model_data_config(self.model)
        self.transform = create_transform(**cfg, is_training=False)
        self._lock = threading.Lock()
        self.backend = "timm"
        self.provider = f"timm/{self.device}"

        num_classes = int(getattr(self.model, "num_classes", 1000))
        block_terms = _split_env("IMGEDGE_TIMM_EXCLUDE") or BLOCK_TERMS
        contrast_terms = _split_env("IMGEDGE_TIMM_CONTRAST") or CONTRAST_TERMS
        labels = _imagenet_labels(self.model, num_classes) if (block_terms or contrast_terms) else None
        self.mask = _mask_for(labels, block_terms, num_classes)
        self.contrast_mask = _mask_for(labels, contrast_terms, num_classes)
        self.contrast_term_masks = _masks_by_term(labels, contrast_terms, num_classes)
        self.matched = int(self.mask.sum())
        self.contrast_matched = int(self.contrast_mask.sum())

    def _infer(self, img):
        tensor = self.transform(img.convert("RGB")).unsqueeze(0).to(self.device)
        with self._lock, torch.inference_mode():
            logits = self.model(tensor)
            probs = torch.softmax(logits, dim=1)[0].float().cpu().numpy()
        return probs

    def _sum(self, probs, mask):
        if not mask.any():
            return 0.0
        if mask.shape[0] != probs.shape[0]:  # defensive: shape mismatch
            k = min(mask.shape[0], probs.shape[0])
            return float(probs[:k][mask[:k]].sum())
        return float(probs[mask].sum())

    def assess(self, img):
        if not (self.matched or self.contrast_matched):
            return 0.0, 0.0  # nothing configured -> abstain
        probs = self._infer(img)
        pos = self._sum(probs, self.mask)
        neg = self._sum(probs, self.contrast_mask)
        evidence = pos - self.contrast_weight * neg  # signed, may be negative
        score = max(0.0, min(1.0, evidence))  # [0,1] for discrete votes
        details = {
            "block_p": round(pos, 5),
            "contrast_p": round(neg, 5),
            "contrast_terms": {t: round(self._sum(probs, m), 5) for t, m in self.contrast_term_masks.items()},
        }
        return score, evidence, details

    def score(self, img):
        return self.assess(img)[0]
