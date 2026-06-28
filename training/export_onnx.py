"""Export a fine-tuned MobileNetV3 checkpoint to ONNX for the local classifier.

Writes <out>.onnx plus a sidecar <out>.json holding the labels and the exact
preprocessing (image size + normalization) so inference stays consistent.

Example:
  python export_onnx.py --checkpoint runs/best.pt --out runs/mobilenetv3.onnx
"""

import argparse
import json
from pathlib import Path

import torch
from torch import nn
from torchvision import models


def build_model(variant, num_classes):
    factory = models.mobilenet_v3_small if variant == "small" else models.mobilenet_v3_large
    model = factory(weights=None)
    in_features = model.classifier[-1].in_features
    model.classifier[-1] = nn.Linear(in_features, num_classes)
    return model


def main():
    p = argparse.ArgumentParser(description="Export a checkpoint to ONNX.")
    p.add_argument("--checkpoint", default="runs/best.pt")
    p.add_argument("--out", default="runs/mobilenetv3.onnx")
    p.add_argument("--opset", type=int, default=17)
    args = p.parse_args()

    ckpt = torch.load(args.checkpoint, map_location="cpu")
    model = build_model(ckpt["variant"], len(ckpt["classes"]))
    model.load_state_dict(ckpt["state_dict"])
    model.eval()

    size = int(ckpt.get("image_size", 224))
    dummy = torch.randn(1, 3, size, size)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    torch.onnx.export(
        model,
        dummy,
        str(out_path),
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=args.opset,
    )

    meta = {
        "classes": ckpt["classes"],
        "image_size": size,
        "mean": ckpt["mean"],
        "std": ckpt["std"],
    }
    out_path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    print(f"Exported {out_path}")
    print(f"Labels + preprocessing: {out_path.with_suffix('.json')}")


if __name__ == "__main__":
    main()
