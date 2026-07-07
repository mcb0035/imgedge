# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Export the timm (ImageNet) voter model to int8 ONNX for in-browser Fast mode.

Loads the pretrained timm model, exports it to ONNX (opset 17), and dynamically
quantizes it to int8 (~6 MB). tools/bundle_inbrowser.py copies the result into
the extension. The output is a build artifact (git-ignored). Needs the optional
deps:

  pip install timm torch onnxruntime
  python tools/convert_timm_to_onnx.py

Model-agnostic: pass --model (with --out) to export another ImageNet-1k
backbone -- e.g. the deit3 third voter:

  python tools/convert_timm_to_onnx.py --model deit3_small_patch16_224 \\
      --out src/imgedge/voters/models/deit3.onnx
"""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "src" / "imgedge" / "voters" / "models" / "timm.onnx"


def main():
    ap = argparse.ArgumentParser(description="Export + quantize the timm voter model to int8 ONNX.")
    ap.add_argument(
        "--model",
        default=None,
        help="timm model to export (default: the timm voter's DEFAULT_MODEL)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output .onnx (default: timm.onnx; required for a non-default --model)",
    )
    ap.add_argument("--opset", type=int, default=17)
    args = ap.parse_args()

    try:
        import timm
        import torch
        from onnxruntime.quantization import QuantType, quantize_dynamic
        from timm.data import resolve_model_data_config

        from imgedge.voters.timm_voter import DEFAULT_MODEL
    except Exception as e:
        raise SystemExit(f"deps missing ({e}). Install: pip install timm torch onnxruntime") from e

    model_name = args.model or DEFAULT_MODEL
    if args.out is not None:
        out = args.out
    elif model_name == DEFAULT_MODEL:
        out = DEFAULT_OUT
    else:
        ap.error(f"--out is required for a non-default --model ({model_name})")

    model = timm.create_model(model_name, pretrained=True).eval()
    size = int(resolve_model_data_config(model)["input_size"][-1])
    out.parent.mkdir(parents=True, exist_ok=True)

    fp32 = out.with_suffix(".fp32.onnx")
    dummy = torch.randn(1, 3, size, size)
    torch.onnx.export(
        model,
        dummy,
        str(fp32),
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=args.opset,
        dynamo=False,
    )
    quantize_dynamic(str(fp32), str(out), weight_type=QuantType.QInt8)
    fp32.unlink(missing_ok=True)
    print(f"Wrote {out} ({out.stat().st_size // 1024} KiB) from {model_name} @ {size}px.")


if __name__ == "__main__":
    main()
