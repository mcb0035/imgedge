# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Bundle the iNat model + ONNX Runtime Web into extension/inbrowser/vendor/.

The in-browser "Fast" classifier (the offscreen document) loads these at
runtime. They are large and NOT committed (see extension/inbrowser/vendor/
.gitignore) -- run this before packaging the extension.

Sources:
  * ONNX model: src/imgedge/inat/models/INatVision_Small_2_fact256_8bit.onnx
    (produce it first with: python src/imgedge/inat/convert_to_onnx.py)
  * timm ONNX model (optional 2nd voter): src/imgedge/voters/models/timm.onnx
    (produce it with: python tools/convert_timm_to_onnx.py)
  * deit3 ONNX model (optional 3rd voter): src/imgedge/voters/models/deit3.onnx
    (produce it with: python tools/convert_timm_to_onnx.py --model deit3_small_patch16_224 --out ...)
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
TIMM_MODEL = ROOT / "src" / "imgedge" / "voters" / "models" / "timm.onnx"
DEIT3_MODEL = ROOT / "src" / "imgedge" / "voters" / "models" / "deit3.onnx"
VENDOR = ROOT / "extension" / "inbrowser" / "vendor"
ORT_CANDIDATES = [
    ROOT / "node_modules" / "onnxruntime-web" / "dist",
    ROOT / "spike" / "inbrowser-fast" / "node_modules" / "onnxruntime-web" / "dist",
]
# The webgpu bundle only needs the JSEP build (WebGPU + its CPU fallback) and the
# asyncify build (its threading/proxy path). The plain build is for the wasm-only
# bundle we don't ship, and jspi is experimental -- `--all` copies every variant
# for maximum browser compatibility (roughly 2x the size).
LEAN_PATTERNS = (
    "ort.webgpu.min.js",
    "ort-wasm-simd-threaded.jsep.wasm",
    "ort-wasm-simd-threaded.jsep.mjs",
    "ort-wasm-simd-threaded.asyncify.wasm",
    "ort-wasm-simd-threaded.asyncify.mjs",
)
ALL_PATTERNS = ("ort.webgpu.min.js", "ort-wasm-*.wasm", "ort-wasm-*.mjs")


def find_ort_dist(override):
    candidates = [Path(override)] if override else ORT_CANDIDATES
    for c in candidates:
        if (c / "ort.webgpu.min.js").exists():
            return c
    raise SystemExit("ONNX Runtime Web not found. Run `npm install onnxruntime-web` or pass --ort-dist <dir>.")


def main():
    ap = argparse.ArgumentParser(description="Bundle the iNat model + ORT Web into the extension.")
    ap.add_argument("--ort-dist", default=None, help="path to onnxruntime-web/dist")
    ap.add_argument("--all", action="store_true", help="copy every ORT wasm variant (max compat, ~2x size)")
    args = ap.parse_args()

    if not MODEL.exists():
        raise SystemExit(f"model not found: {MODEL}\nRun: python src/imgedge/inat/convert_to_onnx.py")

    ort_dist = find_ort_dist(args.ort_dist)
    VENDOR.mkdir(parents=True, exist_ok=True)

    # Clear stale vendored model + ORT builds so a lean rebuild doesn't leave old
    # variants behind (the .gitignore is preserved).
    for old in [*VENDOR.glob("ort*"), VENDOR / "inat.onnx", VENDOR / "timm.onnx", VENDOR / "deit3.onnx"]:
        old.unlink(missing_ok=True)

    shutil.copy2(MODEL, VENDOR / "inat.onnx")
    copied = ["inat.onnx"]
    # Second voter (optional): only bundled once it's been exported.
    if TIMM_MODEL.exists():
        shutil.copy2(TIMM_MODEL, VENDOR / "timm.onnx")
        copied.append("timm.onnx")
    else:
        print(f"note: {TIMM_MODEL} not found -- timm voter not bundled (iNat only).")
        print("      produce it with: python tools/convert_timm_to_onnx.py")
    # Optional third voter (deit3): likewise only bundled once it's been exported.
    if DEIT3_MODEL.exists():
        shutil.copy2(DEIT3_MODEL, VENDOR / "deit3.onnx")
        copied.append("deit3.onnx")
    else:
        print(f"note: {DEIT3_MODEL} not found -- deit3 third voter not bundled (optional).")
    for pattern in ALL_PATTERNS if args.all else LEAN_PATTERNS:
        for f in sorted(ort_dist.glob(pattern)):
            shutil.copy2(f, VENDOR / f.name)
            copied.append(f.name)

    print(f"Bundled {len(copied)} files into {VENDOR} (from {ort_dist}):")
    for name in copied:
        print("  " + name)


if __name__ == "__main__":
    main()
