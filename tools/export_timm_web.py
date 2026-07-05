# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Export the in-browser "Fast" mode metadata for the timm (ImageNet) voter.

The second in-browser voter mirrors imgedge.voters.timm_voter: it runs the timm
ImageNet model, softmaxes the logits, and sums probability over the arachnid
classes (minus an optional contrast set). This bakes the pieces the browser
can't derive at runtime -- the input preprocessing constants and the arachnid /
contrast class indices -- into a small JSON, so the extension never ships timm.

It reuses timm_voter's own term lists and whole-word matcher, so the JS port
stays in parity. Re-run whenever the model or terms change (needs the optional
voter deps):

  pip install timm torch
  python tools/export_timm_web.py
"""

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "extension" / "inbrowser" / "timm_web.json"
# Ensemble weight for the timm voter (mirrors IMGEDGE_TIMM_WEIGHT default).
TIMM_WEIGHT = 0.5


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()

    try:
        import timm
        from timm.data import resolve_model_data_config

        from imgedge.voters.timm_voter import (
            BLOCK_TERMS,
            CONTRAST_TERMS,
            CONTRAST_WEIGHT,
            DEFAULT_MODEL,
            _imagenet_labels,
            _mask_for,
        )
    except Exception as e:
        raise SystemExit(f"timm/torch not available ({e}). Install: pip install timm torch") from e

    model = timm.create_model(DEFAULT_MODEL, pretrained=True).eval()
    cfg = resolve_model_data_config(model)
    size = int(cfg["input_size"][-1])
    num_classes = int(getattr(model, "num_classes", 1000))
    labels = _imagenet_labels(model, num_classes)
    block = np.where(_mask_for(labels, BLOCK_TERMS, num_classes))[0].astype(int).tolist()
    contrast = np.where(_mask_for(labels, CONTRAST_TERMS, num_classes))[0].astype(int).tolist()

    payload = {
        "model": DEFAULT_MODEL,
        "target": "Arachnida",
        "num_classes": num_classes,
        # Mirrors timm's create_transform: resize the shorter side then center-
        # crop to `size` (RGB), then (value/255 - mean) / std, laid out NCHW.
        # The model emits logits -> softmax before scoring.
        "input": {
            "height": size,
            "width": size,
            "layout": "NCHW",
            "dtype": "float32",
            "mean": [float(x) for x in cfg["mean"]],
            "std": [float(x) for x in cfg["std"]],
            "crop_pct": float(cfg.get("crop_pct", 0.875)),
            "interpolation": str(cfg.get("interpolation", "bicubic")),
            "softmax": True,
        },
        # evidence = sum(prob[block]) - contrast_weight * sum(prob[contrast]).
        "block_indices": block,
        "contrast_indices": contrast,
        "contrast_weight": float(CONTRAST_WEIGHT),
        "weight": TIMM_WEIGHT,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    print(f"Wrote {args.out}: {len(block)} block / {len(contrast)} contrast of {num_classes} classes.")


if __name__ == "__main__":
    main()
