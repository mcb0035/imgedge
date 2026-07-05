# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Bundle the iNat model + ONNX Runtime Web into extension/inbrowser/vendor/.

The in-browser "Fast" classifier (the offscreen document) loads these at
runtime. They are large and NOT committed (see extension/inbrowser/vendor/
.gitignore) -- run this before packaging the extension.

Sources:
  * ONNX model: src/imgedge/inat/models/INatVision_Small_2_fact256_8bit.onnx
    (produce it first with: python src/imgedge/inat/convert_to_onnx.py)
  * ONNX Runtime Web: the onnxruntime-web npm package's dist/ folder
    (npm install onnxruntime-web). Auto-discovered under node_modules/, or pass
    --ort-dist to point at it.

Run:
  python tools/bundle_inbrowser.py
"""

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "src" / "imgedge" / "inat" / "models" / "INatVision_Small_2_fact256_8bit.onnx"
VENDOR = ROOT / "extension" / "inbrowser" / "vendor"
ORT_CANDIDATES = [
    ROOT / "node_modules" / "onnxruntime-web" / "dist",
    ROOT / "spike" / "inbrowser-fast" / "node_modules" / "onnxruntime-web" / "dist",
]
ORT_PATTERNS = ("ort.webgpu.min.js", "ort-wasm-*.wasm", "ort-wasm-*.mjs")


def find_ort_dist(override):
    candidates = [Path(override)] if override else ORT_CANDIDATES
    for c in candidates:
        if (c / "ort.webgpu.min.js").exists():
            return c
    raise SystemExit(
        "ONNX Runtime Web not found. Run `npm install onnxruntime-web` or pass --ort-dist <dir>."
    )


def main():
    ap = argparse.ArgumentParser(description="Bundle the iNat model + ORT Web into the extension.")
    ap.add_argument("--ort-dist", default=None, help="path to onnxruntime-web/dist")
    args = ap.parse_args()

    if not MODEL.exists():
        raise SystemExit(f"model not found: {MODEL}\nRun: python src/imgedge/inat/convert_to_onnx.py")

    ort_dist = find_ort_dist(args.ort_dist)
    VENDOR.mkdir(parents=True, exist_ok=True)

    shutil.copy2(MODEL, VENDOR / "inat.onnx")
    copied = ["inat.onnx"]
    for pattern in ORT_PATTERNS:
        for f in sorted(ort_dist.glob(pattern)):
            shutil.copy2(f, VENDOR / f.name)
            copied.append(f.name)

    print(f"Bundled {len(copied)} files into {VENDOR} (from {ort_dist}):")
    for name in copied:
        print("  " + name)


if __name__ == "__main__":
    main()
