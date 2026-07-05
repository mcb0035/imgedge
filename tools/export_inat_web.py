# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Export the in-browser "Fast" mode metadata for the iNat model.

The in-browser classifier (see extension/inbrowser/) needs two things the Python
pipeline derives at runtime, baked into a small JSON so the extension never has
to ship or parse the full taxonomy:

  * the pre/post-processing constants (input size, layout, float scaling), and
  * the Arachnida leaf-index mask (which of the model's output indices are
    spiders / scorpions / ticks / mites), computed by walking taxonomy.csv.

This mirrors imgedge.inat.inat_filter.prep_input / postprocess exactly so the JS
port stays in parity. Re-run whenever the model or taxonomy changes:

  python tools/export_inat_web.py
"""

import argparse
import json
from pathlib import Path

import numpy as np

from imgedge.inat.inat_filter import DEFAULT_TARGET, build_mask

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TAXONOMY = ROOT / "src" / "imgedge" / "inat" / "models" / "taxonomy.csv"
DEFAULT_OUT = ROOT / "extension" / "inbrowser" / "inat_web.json"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--target", default=DEFAULT_TARGET)
    args = p.parse_args()

    if not args.taxonomy.exists():
        raise SystemExit(f"taxonomy not found: {args.taxonomy}\nRun: python -m imgedge.inat.download_models")

    mask = build_mask(args.taxonomy, args.target)
    indices = np.where(mask)[0].astype(int).tolist()

    payload = {
        "model": "INatVision_Small_2_fact256_8bit",
        "target": args.target,
        "num_classes": int(mask.shape[0]),
        # Mirrors inat_filter.prep_input for a float32 input: value / divisor + offset,
        # applied to RGB uint8 [0, 255] -> Inception-style [-1, 1].
        "input": {
            "height": 299,
            "width": 299,
            "layout": "NHWC",
            "dtype": "float32",
            "divisor": 127.5,
            "offset": -1.0,
        },
        "arachnida_leaf_indices": indices,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    print(f"Wrote {args.out}: {len(indices)} / {mask.shape[0]} indices are {args.target}.")


if __name__ == "__main__":
    main()
