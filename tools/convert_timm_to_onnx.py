# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Export the timm (ImageNet) voter model to int8 ONNX for in-browser Fast mode.

Loads the pretrained timm model, exports it to ONNX (opset 17), and dynamically
quantizes it to int8 (~6 MB). tools/bundle_inbrowser.py copies the result into
the extension. The output is a build artifact (git-ignored). Needs the optional
deps:

  pip install timm torch onnxruntime
  python tools/convert_timm_to_onnx.py
"""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "src" / "imgedge" / "voters" / "models" / "timm.onnx"


def main():
    ap = argparse.ArgumentParser(description="Export + quantize the timm voter model to int8 ONNX.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
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

    model = timm.create_model(DEFAULT_MODEL, pretrained=True).eval()
    size = int(resolve_model_data_config(model)["input_size"][-1])
    args.out.parent.mkdir(parents=True, exist_ok=True)

    fp32 = args.out.with_suffix(".fp32.onnx")
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
    quantize_dynamic(str(fp32), str(args.out), weight_type=QuantType.QInt8)
    fp32.unlink(missing_ok=True)
    print(f"Wrote {args.out} ({args.out.stat().st_size // 1024} KiB) from {DEFAULT_MODEL} @ {size}px.")


if __name__ == "__main__":
    main()
