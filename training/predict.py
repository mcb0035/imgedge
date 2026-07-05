# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Run the exported ONNX model on one image (sanity check + serving reference).

The preprocessing here mirrors the validation transform in fine_tune.py, so it
also serves as the reference for wiring the model into classifier/server.py.

Example:
  python predict.py path/to/image.jpg --model runs/mobilenetv3.onnx
"""

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image


def softmax(x):
    e = np.exp(x - np.max(x))
    return e / e.sum()


def preprocess(path, size, mean, std):
    img = Image.open(path).convert("RGB")
    short = int(round(size * 1.14))
    w, h = img.size
    if w < h:
        new_w, new_h = short, int(round(h * short / w))
    else:
        new_w, new_h = int(round(w * short / h)), short
    img = img.resize((new_w, new_h), Image.BILINEAR)
    left = (new_w - size) // 2
    top = (new_h - size) // 2
    img = img.crop((left, top, left + size, top + size))

    arr = np.asarray(img, dtype="float32") / 255.0
    arr = (arr - mean) / std
    arr = arr.transpose(2, 0, 1)[None]  # HWC -> NCHW
    return arr.astype("float32")


def main():
    p = argparse.ArgumentParser(description="Classify an image with the exported ONNX model.")
    p.add_argument("image")
    p.add_argument("--model", default="runs/mobilenetv3.onnx")
    args = p.parse_args()

    meta = json.loads(Path(args.model).with_suffix(".json").read_text())
    mean = np.array(meta["mean"], dtype="float32")
    std = np.array(meta["std"], dtype="float32")

    session = ort.InferenceSession(args.model, providers=["CPUExecutionProvider"])
    x = preprocess(args.image, meta["image_size"], mean, std)
    logits = session.run(None, {"input": x})[0][0]
    probs = softmax(logits)

    for name, prob in sorted(zip(meta["classes"], probs), key=lambda t: -t[1]):
        print(f"{name:20s} {prob:.4f}")


if __name__ == "__main__":
    main()
