"""Block images of a target taxon (default: class Arachnida) using the
iNaturalist vision model — fully local, no training.

For each image it sums the probability mass the model assigns to taxa that
descend from the target taxon (Arachnida -> spiders, scorpions, ticks...). If
that mass crosses a threshold, the caller blocks the image.

This module holds the shared pieces (taxonomy mask, decode hardening, pre/post
processing) plus the TFLite backend (`TaxonFilter`, with a small interpreter
pool for parallel inference). The ONNX GPU/NPU backend lives in onnx_filter.py
and reuses the same helpers.
"""

import csv
import io
import queue

import numpy as np
from PIL import Image

from inat_vision import dequantize, get_interpreter_cls

DEFAULT_TARGET = "Arachnida"

# Decode-hardening: cap pixels (decompression-bomb guard) and restrict the image
# formats we even attempt to parse (shrinks the codec attack surface).
Image.MAX_IMAGE_PIXELS = 24_000_000
_ALLOWED_FORMATS = ["JPEG", "PNG", "WEBP", "GIF", "BMP"]


def _load_taxonomy(taxonomy_csv):
    """Return (parent, name, leaf_to_taxon) maps from an iNaturalist taxonomy.csv."""
    parent, name, leaf_to_taxon = {}, {}, {}
    with open(taxonomy_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = [c.lower() for c in (reader.fieldnames or [])]
        orig = reader.fieldnames or []

        def col(*cands):
            for c in cands:
                if c in cols:
                    return orig[cols.index(c)]
            return None

        tid_c = col("taxon_id", "id")
        par_c = col("parent_taxon_id", "parent_id", "parent")
        name_c = col("name", "taxon_name")
        leaf_c = col("leaf_class_id", "leafclassid", "leaf_class")
        if not tid_c:
            raise ValueError("taxonomy.csv: no taxon_id column found")

        for row in reader:
            try:
                tid = int(float(row[tid_c]))
            except (TypeError, ValueError):
                continue
            name[tid] = (row.get(name_c) or "").strip()
            praw = row.get(par_c) if par_c else None
            try:
                parent[tid] = int(float(praw)) if praw not in (None, "") else None
            except ValueError:
                parent[tid] = None
            if leaf_c and row.get(leaf_c) not in (None, ""):
                try:
                    leaf_to_taxon[int(float(row[leaf_c]))] = tid
                except ValueError:
                    pass
    return parent, name, leaf_to_taxon


def build_mask(taxonomy_csv, target):
    """Boolean mask over model output indices: True where the leaf taxon descends
    from `target` (e.g. every spider/scorpion/tick under Arachnida)."""
    parent, name, leaf_to_taxon = _load_taxonomy(taxonomy_csv)
    target_lower = target.strip().lower()
    target_ids = {tid for tid, nm in name.items() if nm.lower() == target_lower}
    if not target_ids:
        raise ValueError(f"Target taxon {target!r} not found in taxonomy")

    cache = {}

    def descends(tid):
        chain, result, seen, cur = [], False, 0, tid
        while cur is not None and seen < 500:
            if cur in cache:
                result = cache[cur]
                break
            if cur in target_ids:
                result = True
                break
            chain.append(cur)
            cur = parent.get(cur)
            seen += 1
        for t in chain:
            cache[t] = result
        return result

    n = (max(leaf_to_taxon) + 1) if leaf_to_taxon else 0
    mask = np.zeros(n, dtype=bool)
    for leaf_idx, tid in leaf_to_taxon.items():
        if 0 <= leaf_idx < n and descends(tid):
            mask[leaf_idx] = True
    return mask


def open_guarded(raw):
    """Open image bytes with decode hardening (use within a `with`). Rejects
    decompression bombs before any heavy decode and only parses known raster
    formats — a defense against crafted inline image payloads."""
    img = Image.open(io.BytesIO(raw), formats=_ALLOWED_FORMATS)
    w, h = img.size
    if w <= 0 or h <= 0 or w * h > Image.MAX_IMAGE_PIXELS:
        img.close()
        raise ValueError("image rejected (size)")
    return img


def prep_input(img, height, width, uint8):
    """Resize to the model input and return an NHWC batch of size 1."""
    img = img.convert("RGB").resize((width, height), Image.BILINEAR)
    arr = np.asarray(img)
    if uint8:
        return np.expand_dims(arr.astype(np.uint8), axis=0)
    return np.expand_dims((arr.astype(np.float32) / 127.5) - 1.0, axis=0)


def postprocess(out, mask):
    """Sum the non-negative, normalized probability mass under `mask`."""
    out = np.clip(np.asarray(out, dtype=np.float32), 0, None)
    total = float(out.sum())
    if total > 0:
        out = out / total
    if mask.shape[0] != out.shape[0]:
        k = min(mask.shape[0], out.shape[0])
        return float(out[:k][mask[:k]].sum())
    return float(out[mask].sum())


class TaxonFilter:
    """TFLite backend with a pool of interpreters for parallel inference."""

    backend = "tflite"

    def __init__(self, model_path, taxonomy_csv, target=DEFAULT_TARGET, pool_size=1):
        interpreter_cls = get_interpreter_cls()
        pool_size = max(1, int(pool_size))
        self._interps = queue.Queue()
        first = None
        for _ in range(pool_size):
            interp = interpreter_cls(model_path=str(model_path))
            interp.allocate_tensors()
            if first is None:
                first = interp
            self._interps.put(interp)
        # Tensor specs are identical across interpreters loaded from one model.
        self.in_detail = first.get_input_details()[0]
        self.out_detail = first.get_output_details()[0]
        shape = self.in_detail["shape"]
        self._hw = (int(shape[1]), int(shape[2]))
        self._uint8 = self.in_detail["dtype"] == np.uint8
        self.pool_size = pool_size
        self.provider = f"CPU x{pool_size}"
        self.target = target
        self.mask = build_mask(taxonomy_csv, target)
        self.match_count = int(self.mask.sum())

    def score(self, img):
        """Return P(image depicts the target taxon) in [0, 1]."""
        data = prep_input(img, self._hw[0], self._hw[1], self._uint8)
        interp = self._interps.get()  # decode happened above, outside the wait
        try:
            interp.set_tensor(self.in_detail["index"], data)
            interp.invoke()
            out = interp.get_tensor(self.out_detail["index"])[0]
        finally:
            self._interps.put(interp)
        return postprocess(dequantize(out, self.out_detail), self.mask)

    def score_bytes(self, raw):
        with open_guarded(raw) as img:
            return self.score(img)
