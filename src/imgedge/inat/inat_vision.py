"""Run the iNaturalist vision TFLite model on an image (species identification).

This loads the quantized .tflite, reads the input/output tensor specs directly
from the model (so the image size and dtype are never hard-coded), preprocesses
the image to match, runs inference, and maps the top predictions to taxon names
via taxonomy.csv.

IMPORTANT — verify against iNaturalist's reference pipeline:
  Two details are convention-specific and worth confirming against the official
  inference code (https://github.com/inaturalist/inatVisionAPI):
    1. Float input normalization. Quantized models usually take uint8 [0,255]
       directly (handled here). If the model's input is float32, this uses the
       Inception-style [-1, 1] scaling iNaturalist models commonly expect.
    2. Output index -> taxon mapping. This assumes the output vector is indexed
       by `leaf_class_id` from taxonomy.csv (the standard iNat export layout).

Example:
  python inat_vision.py photo.jpg \
      --model models/INatVision_Small_2_fact256_8bit.tflite \
      --taxonomy models/taxonomy.csv --topk 5
"""

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def get_interpreter_cls():
    """Prefer the lightweight LiteRT runtime, fall back to full TensorFlow."""
    try:
        from ai_edge_litert.interpreter import Interpreter  # type: ignore

        return Interpreter
    except Exception:
        pass
    try:
        import tensorflow as tf  # type: ignore

        return tf.lite.Interpreter
    except Exception as e:
        sys.exit(
            "No TFLite runtime found. Install one of:\n"
            "  pip install ai-edge-litert   (Linux/macOS)\n"
            "  pip install tensorflow       (Windows)\n"
            f"Import error: {e}"
        )


def load_labels(taxonomy_csv):
    """Map model output index -> taxon name using taxonomy.csv (best effort)."""
    labels = {}
    path = Path(taxonomy_csv)
    if not path.exists():
        return labels
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = [c.lower() for c in (reader.fieldnames or [])]
        original = reader.fieldnames or []

        def find(*candidates):
            for cand in candidates:
                if cand in cols:
                    return original[cols.index(cand)]
            return None

        leaf_col = find("leaf_class_id", "leafclassid", "leaf_class")
        name_col = find("name", "taxon_name", "preferred_common_name")
        id_col = find("taxon_id", "id")

        for i, row in enumerate(reader):
            key = None
            if leaf_col and row.get(leaf_col) not in (None, ""):
                try:
                    key = int(float(row[leaf_col]))
                except ValueError:
                    key = None
            if key is None and not leaf_col:
                key = i  # fall back to row order
            if key is None:
                continue
            labels[key] = row.get(name_col) or (row.get(id_col) if id_col else None) or str(key)
    return labels


def preprocess(image_path, input_detail):
    shape = input_detail["shape"]
    height, width = int(shape[1]), int(shape[2])
    img = Image.open(image_path).convert("RGB").resize((width, height), Image.BILINEAR)
    arr = np.asarray(img)
    if input_detail["dtype"] == np.uint8:
        data = arr.astype(np.uint8)
    else:
        # Inception-style scaling to [-1, 1] for float inputs.
        data = (arr.astype(np.float32) / 127.5) - 1.0
    return np.expand_dims(data, axis=0)


def dequantize(values, detail):
    scale, zero = detail.get("quantization", (0.0, 0))
    if detail["dtype"] in (np.uint8, np.int8) and scale:
        return (values.astype(np.float32) - zero) * scale
    return values.astype(np.float32)


def predict(image_path, model_path, labels, topk=5):
    Interpreter = get_interpreter_cls()
    interp = Interpreter(model_path=str(model_path))
    interp.allocate_tensors()
    in_detail = interp.get_input_details()[0]
    out_detail = interp.get_output_details()[0]

    interp.set_tensor(in_detail["index"], preprocess(image_path, in_detail))
    interp.invoke()
    scores = dequantize(interp.get_tensor(out_detail["index"])[0], out_detail)

    top = np.argsort(scores)[::-1][:topk]
    return [(int(i), labels.get(int(i), f"#{int(i)}"), float(scores[i])) for i in top]


def main():
    p = argparse.ArgumentParser(description="Identify species with the iNaturalist vision model.")
    p.add_argument("image")
    p.add_argument("--model", default="models/INatVision_Small_2_fact256_8bit.tflite")
    p.add_argument("--taxonomy", default="models/taxonomy.csv")
    p.add_argument("--topk", type=int, default=5)
    args = p.parse_args()

    labels = load_labels(args.taxonomy)
    if not labels:
        print(f"Warning: no labels loaded from {args.taxonomy}; showing raw indices.")

    for idx, name, score in predict(args.image, args.model, labels, args.topk):
        print(f"{score:8.4f}  [{idx}] {name}")


if __name__ == "__main__":
    main()
