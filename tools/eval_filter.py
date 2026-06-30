#!/usr/bin/env python3
"""ImgEdge filtering evaluation harness.

Run the REAL classification pipeline over a labelled dataset and report
recall / false-positive rate, a threshold sweep, and a salience-strategy
comparison -- WITHOUT ever displaying, extracting, or writing any image.

Why the care: ImgEdge exists so a user never has to see a category of image
(by default arachnids). Evaluating it means running it against exactly those
images, so the operator must be able to measure quality without ever being
shown one -- not even as a file thumbnail or an editor preview.

How this tool keeps the images unseen:
  * The dataset is read straight from an AES-encrypted .zip (via pyzipper). The
    OS shell and editors cannot generate previews/thumbnails of encrypted
    archive members, and the plaintext images never exist as loose files.
  * Image bytes are decoded only in memory and only as far as classification
    needs; pixels are never rendered, re-saved, or logged.
  * All output is text/numbers: counts, rates, and per-file SCORES (filename +
    numeric breakdown). No image data is ever written or shown.

Dataset layout (paths inside the encrypted zip, or subfolders of a plain dir):
    block/...   images that SHOULD be blocked (positives)
    allow/...   images that should NOT be blocked (negatives)

Typical use:
    # 1) Build the encrypted dataset once, without ever opening an image --
    #    fetch a list of "label,url" lines you trust to be the target category:
    python tools/eval_filter.py build-urls urls.txt dataset.eval.zip
    #    ...or encrypt a folder you assembled by other means, then delete it:
    python tools/eval_filter.py build-dir ./eval-raw dataset.eval.zip

    # 2) Evaluate (password from $IMGEDGE_EVAL_PASSWORD or a no-echo prompt):
    python tools/eval_filter.py eval dataset.eval.zip
    python tools/eval_filter.py eval dataset.eval.zip --threshold 0.35 --report out.json

Requires the model locally (`imgedge-download-models`) and, for encrypted
datasets, the eval extra (`pip install -e ".[eval]"`). This tool is for local
development only; it is never part of the distributed extension.
"""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import sys
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
DEFAULT_SWEEP = [round(0.05 * i, 2) for i in range(1, 19)]  # 0.05 .. 0.90
MAX_FETCH_BYTES = 8 * 1024 * 1024  # mirror the server's per-image cap


# --------------------------------------------------------------------------- #
# Dataset input (never extracts or renders -- bytes go straight to memory)
# --------------------------------------------------------------------------- #
def _label_for(name):
    n = name.replace("\\", "/").lstrip("./")
    if n.startswith("block/"):
        return "block"
    if n.startswith("allow/"):
        return "allow"
    return None


def _iter_dir(root, only=None):
    for label in ("block", "allow"):
        base = Path(root) / label
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                name = f"{label}/{f.relative_to(base).as_posix()}"
                if only is None or name in only:
                    yield label, name, f.read_bytes()


def _iter_zip(zip_path, password, only=None):
    try:
        import pyzipper
    except ModuleNotFoundError as e:
        raise SystemExit('Encrypted datasets need pyzipper: pip install -e ".[eval]"') from e
    pw = password.encode("utf-8") if password else None
    try:
        with pyzipper.AESZipFile(zip_path) as zf:
            if pw:
                zf.setpassword(pw)
            for info in zf.infolist():
                if info.is_dir():
                    continue
                label = _label_for(info.filename)
                if label is None or Path(info.filename).suffix.lower() not in IMAGE_EXTS:
                    continue
                if only is not None and info.filename not in only:
                    continue
                yield label, info.filename, zf.read(info)
    except RuntimeError as e:
        raise SystemExit(f"Could not read encrypted zip (wrong password?): {e}") from e


def iter_samples(path, password=None, only=None):
    """Yield (label, name, raw_bytes) for every labelled image in `path`.

    `path` is an AES-encrypted .zip or a directory with block/ and allow/
    subfolders. Bytes are read into memory only; nothing is extracted to disk.
    `only`, if given, restricts output to that set of names (for sampling).
    """
    p = Path(path)
    if p.is_dir():
        yield from _iter_dir(p, only)
    elif p.suffix.lower() == ".zip":
        yield from _iter_zip(p, password, only)
    else:
        raise SystemExit(f"Dataset must be a directory or a .zip: {path}")


def _labeled_names(path, password=None):
    """Yield (label, name) for labelled entries WITHOUT reading image bytes.
    Zip entry names are not encrypted, so listing needs no password."""
    p = Path(path)
    if p.is_dir():
        for label in ("block", "allow"):
            base = p / label
            if base.is_dir():
                for f in sorted(base.rglob("*")):
                    if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                        yield label, f"{label}/{f.relative_to(base).as_posix()}"
        return
    if p.suffix.lower() == ".zip":
        try:
            import pyzipper
        except ModuleNotFoundError as e:
            raise SystemExit('Encrypted datasets need pyzipper: pip install -e ".[eval]"') from e
        with pyzipper.AESZipFile(p) as zf:
            for info in zf.infolist():
                label = _label_for(info.filename)
                if not info.is_dir() and label and Path(info.filename).suffix.lower() in IMAGE_EXTS:
                    yield label, info.filename
        return
    raise SystemExit(f"Dataset must be a directory or a .zip: {path}")


def _sample_names(path, password, sample_per_class, seed):
    """Pick a random up-to-N names per class (the names list is read without
    decrypting any image)."""
    import random

    rng = random.Random(seed)
    by_label = {}
    for label, name in _labeled_names(path, password):
        by_label.setdefault(label, []).append(name)
    only = set()
    for names in by_label.values():
        rng.shuffle(names)
        only.update(names[:sample_per_class])
    return only


# --------------------------------------------------------------------------- #
# Classification (reuses the exact pipeline the server runs)
# --------------------------------------------------------------------------- #
def load_pipeline():
    """Build the real voting ensemble the server uses."""
    from imgedge.classifier.server import load_ensemble

    ens = load_ensemble()
    if ens is None:
        raise SystemExit(
            "No classifier available. Download the model first:\n"
            "  imgedge-download-models\n"
            'and optionally enable the second voter:  pip install -e ".[voters]"'
        )
    return ens


def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def classify_sample(ens, raw, threshold=None, salience=None):
    """Return a flat record for one image's verdict (no pixels retained). A
    decode/classify failure (e.g. an oversized image the guard rejects) is
    recorded as not-blocked -- matching the server's fail-open behaviour -- so a
    single bad image never aborts a whole run."""
    try:
        verdict = ens.classify_bytes(raw, None, None, threshold, salience)
    except Exception:
        return {
            "block": False,
            "combined": 0.0,
            "thr": None,
            "pos": None,
            "neg": None,
            "mult": None,
            "inat": None,
            "timm_block": None,
            "timm_contrast": None,
            "contrast_terms": None,
            "siglip": None,
            "salience": None,
            "votes": {},
            "error": True,
        }
    dbg = verdict.get("dbg") or {}
    voters = {v.get("name", ""): v for v in dbg.get("voters", [])}
    inat_v = next((v for n, v in voters.items() if n.startswith("inat")), None)
    timm_v = next((v for n, v in voters.items() if n.startswith("timm")), None)
    siglip_v = next((v for n, v in voters.items() if n.startswith("siglip")), None)
    timm_d = (timm_v or {}).get("details") or {}
    return {
        "block": bool(verdict.get("block")),
        "combined": float(verdict.get("score", 0.0)),
        "thr": _as_float(dbg.get("threshold")),
        "pos": _as_float(dbg.get("pos")),
        "neg": _as_float(dbg.get("neg")),
        "mult": _as_float(dbg.get("mult")),
        "inat": _as_float(inat_v.get("score")) if inat_v else None,
        "timm_block": _as_float(timm_d.get("block_p")),
        "timm_contrast": _as_float(timm_d.get("contrast_p")),
        "contrast_terms": timm_d.get("contrast_terms"),
        "siglip": _as_float(siglip_v.get("score")) if siglip_v else None,
        "salience": dbg.get("salience"),
        "votes": verdict.get("votes", {}),
    }


def evaluate(path, threshold=None, salience=None, password=None, sample_per_class=None, seed=1234):
    """Classify labelled images; return records with label + scores only.
    `sample_per_class` scores a random N per class instead of the whole set."""
    ens = load_pipeline()
    only = _sample_names(path, password, sample_per_class, seed) if sample_per_class else None
    records = []
    for label, name, raw in iter_samples(path, password, only):
        rec = classify_sample(ens, raw, threshold, salience)
        rec["label"] = label
        rec["name"] = name
        records.append(rec)
        del raw  # drop the bytes promptly
    return records


# --------------------------------------------------------------------------- #
# Metrics (pure functions -- no models, no I/O; unit-tested)
# --------------------------------------------------------------------------- #
def _predict(rec, threshold):
    return rec["block"] if threshold is None else rec["combined"] >= threshold


def confusion(records, threshold=None):
    tp = fp = tn = fn = 0
    for r in records:
        pred = _predict(r, threshold)
        positive = r["label"] == "block"
        if positive and pred:
            tp += 1
        elif positive:
            fn += 1
        elif pred:
            fp += 1
        else:
            tn += 1
    return tp, fp, tn, fn


def metrics(tp, fp, tn, fn):
    pos = tp + fn
    neg = tn + fp
    recall = tp / pos if pos else math.nan
    fpr = fp / neg if neg else math.nan
    precision = tp / (tp + fp) if (tp + fp) else math.nan
    denom = precision + recall
    f1 = (2 * precision * recall / denom) if denom and not math.isnan(denom) else math.nan
    return {
        "n": pos + neg,
        "pos": pos,
        "neg": neg,
        "recall": recall,
        "fpr": fpr,
        "precision": precision,
        "f1": f1,
    }


def sweep(records, thresholds=None):
    return [{"threshold": t, **metrics(*confusion(records, t))} for t in (thresholds or DEFAULT_SWEEP)]


def _combine(pos, neg, mult):
    return max(0.0, min(1.0, pos * mult + neg))


def salience_variants(records, threshold):
    """Compare salience strategies analytically from each record's pos/neg/mult,
    so alternatives are measured without re-running inference:

        baseline    clamp(pos*mult + neg)          (current behaviour)
        off         clamp(pos + neg)               (salience ignored)
        boost_only  clamp(pos*max(1, mult) + neg)  (salience never suppresses)
    """
    usable = [r for r in records if None not in (r["pos"], r["neg"], r["mult"])]
    rules = {
        "baseline": lambda r: _combine(r["pos"], r["neg"], r["mult"]),
        "off": lambda r: _combine(r["pos"], r["neg"], 1.0),
        "boost_only": lambda r: _combine(r["pos"], r["neg"], max(1.0, r["mult"])),
    }
    out = {"_n_usable": len(usable)}
    for name, rule in rules.items():
        recs = [{"label": r["label"], "combined": rule(r), "block": rule(r) >= threshold} for r in usable]
        out[name] = metrics(*confusion(recs, None))
    return out


def misses(records, threshold=None):
    fns = [r for r in records if r["label"] == "block" and not _predict(r, threshold)]
    fps = [r for r in records if r["label"] == "allow" and _predict(r, threshold)]
    fns.sort(key=lambda r: r["combined"])  # closest-to-caught last; worst first
    fps.sort(key=lambda r: r["combined"], reverse=True)  # most-wrong first
    return fns, fps


# --------------------------------------------------------------------------- #
# Report assembly + text rendering (numbers only)
# --------------------------------------------------------------------------- #
def _round(v, nd=4):
    return None if v is None else round(v, nd)


def _miss_row(r):
    return {
        "name": r["name"],
        "combined": round(r["combined"], 4),
        "pos": _round(r["pos"]),
        "neg": _round(r["neg"]),
        "mult": _round(r["mult"]),
        "votes": r.get("votes", {}),
    }


def _score_row(r):
    return {
        "label": r["label"],
        "combined": round(r["combined"], 4),
        "pos": _round(r["pos"]),
        "neg": _round(r["neg"]),
        "mult": _round(r["mult"]),
        "inat": _round(r.get("inat")),
        "timm_block": _round(r.get("timm_block")),
        "timm_contrast": _round(r.get("timm_contrast")),
        "contrast_terms": r.get("contrast_terms"),
        "siglip": _round(r.get("siglip")),
        "salience": r.get("salience"),
    }


def _op_threshold(records, override):
    if override is not None:
        return override
    for r in records:
        if r.get("thr") is not None:
            return r["thr"]
    return 0.5


def build_report(records, threshold, salience, sweep_on=True):
    fns, fps = misses(records, threshold)
    rep = {
        "samples": len(records),
        "positives": sum(1 for r in records if r["label"] == "block"),
        "negatives": sum(1 for r in records if r["label"] == "allow"),
        "errors": sum(1 for r in records if r.get("error")),
        "operating_point": {
            "threshold": threshold,
            "salience": salience,
            **metrics(*confusion(records, threshold)),
        },
        "false_negatives": [_miss_row(r) for r in fns],
        "false_positives": [_miss_row(r) for r in fps],
        "records": [_score_row(r) for r in records],
    }
    if sweep_on:
        rep["threshold_sweep"] = sweep(records)
        rep["salience_variants"] = salience_variants(records, _op_threshold(records, threshold))
    return rep


def _pct(x):
    return "  n/a" if (x is None or math.isnan(x)) else f"{100 * x:5.1f}%"


def print_report(rep):
    op = rep["operating_point"]
    thr = op["threshold"]
    sal = op["salience"]
    print(f"Samples: {rep['samples']}  (block={rep['positives']}, allow={rep['negatives']})")
    if rep.get("errors"):
        print(f"  ({rep['errors']} images skipped -- decode/classify error, counted as not-blocked)")
    print(
        f"Operating point: threshold={'default' if thr is None else thr}, salience={'default' if sal is None else sal}"
    )
    print(f"  recall (caught) : {_pct(op['recall'])}   <- the number that matters most for a phobia filter")
    print(f"  false positives : {_pct(op['fpr'])}")
    print(f"  precision / F1  : {_pct(op['precision'])} / {_pct(op['f1'])}")

    if "threshold_sweep" in rep:
        print("\nThreshold sweep (block when combined >= t):")
        print("    t      recall     FPR    precision")
        for row in rep["threshold_sweep"]:
            print(f"  {row['threshold']:.2f}    {_pct(row['recall'])}   {_pct(row['fpr'])}   {_pct(row['precision'])}")

    if "salience_variants" in rep:
        sv = rep["salience_variants"]
        print(f"\nSalience strategy comparison (n={sv.get('_n_usable', 0)} with a breakdown):")
        for name in ("baseline", "off", "boost_only"):
            if name in sv:
                m = sv[name]
                print(f"  {name:11s} recall {_pct(m['recall'])}    FPR {_pct(m['fpr'])}")

    if rep["false_negatives"]:
        rows = rep["false_negatives"]
        print(f"\nMissed positives (FN) -- {len(rows)} not blocked (filename + scores only):")
        for r in rows[:50]:
            print(
                f"  {r['name'][:44]:44s} combined={r['combined']:.3f}  pos={r['pos']}  neg={r['neg']}  mult={r['mult']}"
            )

    if rep["false_positives"]:
        rows = rep["false_positives"]
        print(f"\nFalse alarms (FP) -- {len(rows)} wrongly blocked:")
        for r in rows[:50]:
            print(
                f"  {r['name'][:44]:44s} combined={r['combined']:.3f}  pos={r['pos']}  neg={r['neg']}  mult={r['mult']}"
            )


# --------------------------------------------------------------------------- #
# Building encrypted datasets (so collection never requires viewing an image)
# --------------------------------------------------------------------------- #
def _write_zip(out_zip, password, entries):
    """Write (arcname, bytes) pairs into an AES-256 encrypted zip."""
    try:
        import pyzipper
    except ModuleNotFoundError as e:
        raise SystemExit('Building encrypted datasets needs pyzipper: pip install -e ".[eval]"') from e
    if not password:
        raise SystemExit("A password is required to build an encrypted dataset.")
    n = 0
    with pyzipper.AESZipFile(out_zip, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(password.encode("utf-8"))
        for arc, data in entries:
            zf.writestr(arc, data)
            n += 1
    return n


def build_dir(src_dir, out_zip, password):
    n = _write_zip(out_zip, password, ((name, raw) for _, name, raw in _iter_dir(src_dir)))
    print(f"Wrote {n} images into {out_zip} (AES-256). You can now delete {src_dir}.")


def _sniff_ext(data):
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"BM":
        return ".bmp"
    return ".jpg"


def _split_label_url(line):
    for sep in (",", "\t", " "):
        if sep in line:
            label, url = line.split(sep, 1)
            return label.strip().lower(), url.strip()
    return line.lower(), ""


def _fetch(url, timeout=15):
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(MAX_FETCH_BYTES + 1)
    except (urllib.error.URLError, OSError) as e:
        print(f"skip (fetch failed): {url} ({e})", file=sys.stderr)
        return None
    if len(data) > MAX_FETCH_BYTES:
        print(f"skip (too large): {url}", file=sys.stderr)
        return None
    return data


def build_urls(urls_file, out_zip, password):
    """Fetch a list of "label,url" lines into an encrypted zip. The bytes go
    straight from the network into the archive; no image is ever displayed."""
    lines = Path(urls_file).read_text(encoding="utf-8").splitlines()
    counts = {"block": 0, "allow": 0}

    def gen():
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            label, url = _split_label_url(line)
            if label not in ("block", "allow"):
                print(f"skip (need a 'block'/'allow' prefix): {raw_line!r}", file=sys.stderr)
                continue
            if not url.lower().startswith(("http://", "https://")):
                print(f"skip (only http/https): {url}", file=sys.stderr)
                continue
            data = _fetch(url)
            if data is None:
                continue
            counts[label] += 1
            yield f"{label}/{counts[label]:04d}{_sniff_ext(data)}", data

    n = _write_zip(out_zip, password, gen())
    print(f"Wrote {n} images ({counts['block']} block / {counts['allow']} allow) into {out_zip} (AES-256).")
    print("No image was displayed at any point.")


# --------------------------------------------------------------------------- #
# Synthetic datasets (procedural images for a no-real-data tuning / smoke pass)
# --------------------------------------------------------------------------- #
# These are crude procedural drawings, not photographs. A single pass is useful
# to confirm the pipeline end to end, measure the false-positive rate on varied
# non-arachnid images, and watch the salience multiplier across sizes. They
# CANNOT stand in for real-photo recall (the iNat model is trained on real
# organisms and scores drawings low) and so cannot exercise the iNat-confidence
# override. Generated images go straight into the encrypted zip, never shown.
def _rand_color(rng):
    return (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))


def _png_bytes(img):
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _draw_spider(draw, w, h, rng):
    cx, cy = w / 2, h / 2
    unit = max(3, min(w, h) // 9)
    col = (rng.randint(0, 70), rng.randint(0, 70), rng.randint(0, 70))
    width = max(1, unit // 3)
    for k in range(4):  # four legs per side, two segments each, radiating out
        dy = (k - 1.5) * unit * 0.7
        for side in (-1, 1):
            knee = (cx + side * unit * 2.4, cy + dy - unit * 0.6)
            foot = (cx + side * unit * (3.6 + rng.random()), cy + dy + unit * 1.3)
            draw.line([(cx, cy + dy * 0.4), knee, foot], fill=col, width=width, joint="curve")
    draw.ellipse([cx - unit, cy - unit * 0.4, cx + unit, cy + unit * 2.2], fill=col)  # abdomen
    draw.ellipse([cx - unit * 0.6, cy - unit * 1.6, cx + unit * 0.6, cy + unit * 0.2], fill=col)  # cephalothorax


def _draw_negative(draw, w, h, rng):
    kind = rng.choice(("shapes", "bars", "rings", "blank"))
    if kind == "blank":
        return
    for _ in range(rng.randint(2, 6)):
        x0, y0, x1, y1 = rng.randint(0, w), rng.randint(0, h), rng.randint(0, w), rng.randint(0, h)
        box = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        col = _rand_color(rng)
        if kind == "rings":
            draw.ellipse(box, outline=col, width=max(1, w // 40))
        elif kind == "bars":
            draw.rectangle(box, fill=col)
        else:
            (draw.ellipse if rng.random() < 0.5 else draw.rectangle)(box, fill=col)


def build_synthetic(out_zip, password, count=30, seed=1234):
    """Generate `count` procedural arachnid drawings (block/) and `count`
    non-arachnid images (allow/) straight into an AES zip. Nothing is displayed."""
    import random

    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    sizes = (48, 64, 96, 128, 160, 224, 320, 400)

    def gen():
        for label, paint in (("block", _draw_spider), ("allow", _draw_negative)):
            for i in range(count):
                size = rng.choice(sizes)
                img = Image.new("RGB", (size, size), _rand_color(rng))
                paint(ImageDraw.Draw(img), size, size, rng)
                yield f"{label}/{i:04d}.png", _png_bytes(img)

    n = _write_zip(out_zip, password, gen())
    print(f"Wrote {n} synthetic images ({count} block / {count} allow) into {out_zip} (AES-256).")
    print("Procedural drawings only -- no real photo, nothing displayed.")


# --------------------------------------------------------------------------- #
# iNaturalist 2021 dataset sorter (visipedia/inat_comp 2021)
# --------------------------------------------------------------------------- #
# Sort an iNat 2021 dataset into block/ (taxonomic class == "Arachnida") and
# allow/ (everything else) using the COCO-style metadata, writing a balanced
# subset STRAIGHT into the encrypted zip. Nothing is extracted to loose files
# and nothing is displayed, so an arachnid set is assembled without ever
# rendering an image. Per the iNat terms of use the images are not
# redistributable; the encrypted zip is local-only (gitignored) -- never commit.
def _load_inat_meta(meta_path):
    p = Path(meta_path)
    name = p.name.lower()
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        import tarfile

        with tarfile.open(p, "r:*") as tf:
            member = next((m for m in tf.getmembers() if m.name.endswith(".json")), None)
            if member is None:
                raise SystemExit(f"No .json inside {meta_path}")
            return json.load(tf.extractfile(member))
    if name.endswith(".zip"):
        import zipfile

        with zipfile.ZipFile(p) as zf:
            jn = next((n for n in zf.namelist() if n.endswith(".json")), None)
            if jn is None:
                raise SystemExit(f"No .json inside {meta_path}")
            return json.loads(zf.read(jn))
    return json.loads(p.read_text(encoding="utf-8"))


def _iter_inat_images(images_path, wanted):
    """Yield (file_name, bytes) for members named in `wanted` from a directory,
    a tar(.gz), or a zip -- streaming, without extracting anything to disk."""
    p = Path(images_path)
    if p.is_dir():
        for fn in wanted:
            f = p / fn
            if f.is_file():
                yield fn, f.read_bytes()
        return
    name = p.name.lower()
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        import tarfile

        with tarfile.open(p, "r:*") as tf:
            for m in tf:
                key = m.name.lstrip("./")
                if m.isfile() and key in wanted:
                    fobj = tf.extractfile(m)
                    if fobj is not None:
                        yield key, fobj.read()
        return
    if name.endswith(".zip"):
        import zipfile

        with zipfile.ZipFile(p) as zf:
            for info in zf.infolist():
                key = info.filename.lstrip("./")
                if not info.is_dir() and key in wanted:
                    yield key, zf.read(info)
        return
    raise SystemExit(f"Unsupported images source (use a dir, .tar.gz, or .zip): {images_path}")


def build_inat(images_path, meta_path, out_zip, password, limit_per_class=200, seed=1234):
    """Sort an iNat 2021 dataset by taxonomy into block(arachnid)/allow inside an
    encrypted zip, using the metadata JSON. Streams from the image archive; never
    extracts loose files or displays anything."""
    import random

    rng = random.Random(seed)
    meta = _load_inat_meta(meta_path)
    cats = {c["id"]: c for c in meta.get("categories", [])}
    arachnid_ids = {cid for cid, c in cats.items() if (c.get("class") or "").strip().lower() == "arachnida"}
    if not arachnid_ids:
        raise SystemExit("No 'Arachnida' class in categories -- is this iNat 2021 metadata?")
    fname = {im["id"]: im["file_name"] for im in meta.get("images", [])}
    block_files, allow_files = [], []
    for ann in meta.get("annotations", []):
        fn = fname.get(ann["image_id"])
        if fn:
            (block_files if ann["category_id"] in arachnid_ids else allow_files).append(fn)
    if not block_files:
        raise SystemExit("No arachnid images found in the annotations.")
    rng.shuffle(block_files)
    rng.shuffle(allow_files)
    wanted = {fn.lstrip("./"): "block" for fn in block_files[:limit_per_class]}
    wanted.update({fn.lstrip("./"): "allow" for fn in allow_files[:limit_per_class]})

    counts = {"block": 0, "allow": 0}

    def gen():
        for key, data in _iter_inat_images(images_path, wanted):
            label = wanted.get(key)
            if label is None or counts[label] >= limit_per_class:
                continue
            counts[label] += 1
            parts = key.replace("\\", "/").rstrip("/").split("/")
            cat = parts[-2] if len(parts) >= 2 else "_"  # iNat category dir carries the taxonomy
            yield f"{label}/{cat}/{parts[-1]}", data
            if counts["block"] >= limit_per_class and counts["allow"] >= limit_per_class:
                break

    n = _write_zip(out_zip, password, gen())
    print(f"Sorted {n} iNat images: {counts['block']} arachnid -> block, {counts['allow']} other -> allow.")
    print(f"Matched {len(arachnid_ids)} Arachnida categories -> {out_zip} (AES-256). Nothing extracted or shown.")


def _oi_arachnid_mids(descriptions_csv, names):
    """{MID: name} for Open Images classes whose display name is in `names`."""
    import csv

    want = {n.strip().lower() for n in names}
    out = {}
    with open(descriptions_csv, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[1].strip().lower() in want:
                out[row[0].strip()] = row[1].strip()
    return out


def build_openimages(
    images_dir,
    imagelabels_csv,
    descriptions_csv,
    out_zip,
    password,
    arachnid_names=("spider", "scorpion", "tick"),
    limit_per_class=None,
    seed=1234,
):
    """Sort an Open Images split into block(arachnid)/allow inside an encrypted
    zip, using the image-level labels CSV. Reads loose <ImageID>.jpg files from
    `images_dir` and never displays anything. Per the Open Images terms the
    images are not redistributable -- the encrypted zip is local-only."""
    import csv
    import random

    rng = random.Random(seed)
    mid2name = _oi_arachnid_mids(descriptions_csv, arachnid_names)
    if not mid2name:
        raise SystemExit(f"No arachnid classes ({', '.join(arachnid_names)}) found in {descriptions_csv}.")
    arachnid_mids = set(mid2name)

    pos = {}
    with open(imagelabels_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("Confidence") or "0").strip() == "1":
                pos.setdefault(row["ImageID"], set()).add(row["LabelName"].strip())

    root = Path(images_dir)
    block_files, allow_files = [], []
    for img in root.glob("*.jpg"):
        labels = pos.get(img.stem)
        if not labels:
            continue
        (block_files if labels & arachnid_mids else allow_files).append(img.name)
    if not block_files:
        raise SystemExit("No arachnid-labeled images found among the downloaded files.")
    rng.shuffle(block_files)
    rng.shuffle(allow_files)
    cap = limit_per_class or max(len(block_files), len(allow_files))
    wanted = {fn: "block" for fn in block_files[:cap]}
    wanted.update({fn: "allow" for fn in allow_files[:cap]})
    counts = {"block": 0, "allow": 0}

    def gen():
        for fn, label in wanted.items():
            counts[label] += 1
            yield f"{label}/{fn}", (root / fn).read_bytes()

    n = _write_zip(out_zip, password, gen())
    print(f"Sorted {n} Open Images: {counts['block']} arachnid -> block, {counts['allow']} other -> allow.")
    print(f"Arachnid classes: {sorted(mid2name.values())} -> {out_zip} (AES-256). Nothing displayed.")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _get_password(required=True):
    pw = os.environ.get("IMGEDGE_EVAL_PASSWORD")
    if pw:
        return pw
    if not required and not sys.stdin.isatty():
        return None
    return getpass.getpass("Dataset password: ")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="eval_filter",
        description="Evaluate ImgEdge filtering against a labelled dataset (never displays images).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("eval", help="evaluate a dataset (encrypted .zip or directory)")
    pe.add_argument("dataset")
    pe.add_argument("--threshold", type=float, default=None, help="override the block threshold")
    pe.add_argument("--salience", type=float, default=None, help="salience weight 0..1 (0 = off)")
    pe.add_argument("--report", default=None, help="write a JSON report (scores only, no images)")
    pe.add_argument("--no-sweep", action="store_true", help="skip the threshold/salience sweeps")
    pe.add_argument("--sample-per-class", type=int, default=None, help="score a random N per class (sample the set)")
    pe.add_argument("--seed", type=int, default=1234, help="sampling seed")

    pd = sub.add_parser("build-dir", help="encrypt a block/+allow/ folder into an AES zip")
    pd.add_argument("src_dir")
    pd.add_argument("out_zip")

    pu = sub.add_parser("build-urls", help="fetch a label,url list into an AES zip (never shows images)")
    pu.add_argument("urls_file")
    pu.add_argument("out_zip")

    ps = sub.add_parser("build-synthetic", help="generate a procedural labelled dataset (no real images)")
    ps.add_argument("out_zip")
    ps.add_argument("--count", type=int, default=30, help="images per class (default 30)")
    ps.add_argument("--seed", type=int, default=1234, help="RNG seed for reproducibility")

    pi = sub.add_parser("build-inat", help="sort an iNat 2021 dataset into block(arachnid)/allow (AES zip)")
    pi.add_argument("images", help="iNat images: a directory, .tar.gz, or .zip")
    pi.add_argument("metadata", help="iNat metadata: *.json (or .json.tar.gz / .zip)")
    pi.add_argument("out_zip")
    pi.add_argument("--limit-per-class", type=int, default=200, help="max images per class (default 200)")
    pi.add_argument("--seed", type=int, default=1234, help="RNG seed for reproducibility")

    po = sub.add_parser("build-openimages", help="sort an Open Images split into block(arachnid)/allow (AES zip)")
    po.add_argument("images_dir", help="folder of <ImageID>.jpg files")
    po.add_argument("imagelabels_csv", help="...human-imagelabels-boxable.csv (ImageID,Source,LabelName,Confidence)")
    po.add_argument("descriptions_csv", help="oidv7-class-descriptions-boxable.csv (LabelName,DisplayName)")
    po.add_argument("out_zip")
    po.add_argument("--arachnid", default="spider,scorpion,tick", help="comma class names to treat as block")
    po.add_argument("--limit-per-class", type=int, default=None, help="max images per class (default: all)")
    po.add_argument("--seed", type=int, default=1234, help="RNG seed for sampling")

    args = parser.parse_args(argv)

    if args.cmd == "eval":
        password = _get_password(required=str(args.dataset).lower().endswith(".zip"))
        records = evaluate(args.dataset, args.threshold, args.salience, password, args.sample_per_class, args.seed)
        if not records:
            raise SystemExit("No labelled images found (expected block/ and allow/ entries).")
        report = build_report(records, args.threshold, args.salience, sweep_on=not args.no_sweep)
        print_report(report)
        if args.report:
            Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"\nWrote report to {args.report} (scores only, no image data).")
        return 0

    if args.cmd == "build-dir":
        build_dir(args.src_dir, args.out_zip, _get_password())
        return 0

    if args.cmd == "build-urls":
        build_urls(args.urls_file, args.out_zip, _get_password())
        return 0

    if args.cmd == "build-synthetic":
        build_synthetic(args.out_zip, _get_password(), args.count, args.seed)
        return 0

    if args.cmd == "build-inat":
        build_inat(args.images, args.metadata, args.out_zip, _get_password(), args.limit_per_class, args.seed)
        return 0

    if args.cmd == "build-openimages":
        names = [n for n in args.arachnid.split(",") if n.strip()]
        build_openimages(
            args.images_dir,
            args.imagelabels_csv,
            args.descriptions_csv,
            args.out_zip,
            _get_password(),
            names,
            args.limit_per_class,
            args.seed,
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
