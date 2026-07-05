# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Measure how much the in-browser timm resize (a straight 224x224 stretch)
changes verdicts vs. the server's Resize + CenterCrop, on the 2-model combo.

The iNat score is held fixed (read from an eval report), and only the timm
voter is re-run -- once with its normal center-crop transform and once with a
stretch -- so the difference is purely the resize. Reports recall / FPR under
each and how many verdicts flip. Needs the voter deps (timm + torch) and the
encrypted eval dataset:

  # password via $IMGEDGE_EVAL_PASSWORD or an interactive prompt
  python tools/measure_resize.py dataset.eval.zip --report inat_split.json
"""

import argparse
import getpass
import io
import json
import os
from pathlib import Path


def _combine(inat, block_p, contrast_p, cw, tw, thr, inat_override=0.9):
    """Mirror the in-browser 2-model verdict (ensemble.mjs, salience = 1.0)."""
    evidence = block_p - cw * contrast_p
    pos = inat if inat > 0 else 0.0
    neg = 0.0
    if evidence > 0:
        pos += tw * evidence
    elif evidence < 0:
        neg += tw * evidence
    score = max(0.0, min(1.0, pos + neg))
    override = inat >= inat_override
    if override:
        score = max(score, inat)
    return bool(override or score >= thr)


def _metrics(rows):
    tp = fp = tn = fn = 0
    for positive, pred in rows:
        if positive and pred:
            tp += 1
        elif positive:
            fn += 1
        elif pred:
            fp += 1
        else:
            tn += 1
    pos, neg = tp + fn, tn + fp
    recall = tp / pos if pos else 0.0
    fpr = fp / neg if neg else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    return recall, fpr, prec


def main():
    ap = argparse.ArgumentParser(description="Measure the timm resize (stretch vs center-crop) impact.")
    ap.add_argument("dataset", help="encrypted .eval.zip or a block/ + allow/ directory")
    ap.add_argument("--report", required=True, help="eval report JSON (source of the recorded iNat scores)")
    ap.add_argument("--threshold", type=float, default=0.15)
    ap.add_argument("--timm-weight", type=float, default=0.5)
    args = ap.parse_args()

    from eval_filter import iter_samples

    try:
        from PIL import Image
        from timm.data import resolve_model_data_config
        from torchvision import transforms as T

        from imgedge.voters.timm_voter import TimmVoter
    except Exception as e:
        raise SystemExit(f"deps missing ({e}). Install: pip install timm torch") from e

    inat_by_name = {}
    rep = json.loads(Path(args.report).read_text(encoding="utf-8"))
    for r in rep.get("records", []):
        if r.get("inat") is not None:
            inat_by_name[r["name"]] = float(r["inat"])
    if not inat_by_name:
        raise SystemExit(f"no per-image iNat scores in {args.report} (need its `records` array)")

    voter = TimmVoter()
    cw = voter.contrast_weight
    cfg = resolve_model_data_config(voter.model)
    size = int(cfg["input_size"][-1])
    crop_transform = voter.transform  # timm's default Resize + CenterCrop
    stretch_transform = T.Compose(
        [
            T.Resize((size, size), interpolation=T.InterpolationMode.BICUBIC),
            T.ToTensor(),
            T.Normalize(mean=cfg["mean"], std=cfg["std"]),
        ]
    )

    pw = os.environ.get("IMGEDGE_EVAL_PASSWORD")
    if pw is None and str(args.dataset).lower().endswith(".zip"):
        pw = getpass.getpass("Dataset password: ")

    crop_rows, stretch_rows, flips, n = [], [], 0, 0
    for label, name, raw in iter_samples(args.dataset, pw):
        inat = inat_by_name.get(name)
        if inat is None:
            continue  # need the recorded iNat score to hold it fixed
        try:
            img = Image.open(io.BytesIO(raw))
        except Exception:
            continue
        positive = label == "block"
        voter.transform = crop_transform
        cd = voter.assess(img)[2]
        voter.transform = stretch_transform
        sd = voter.assess(img)[2]
        cpred = _combine(inat, cd["block_p"], cd["contrast_p"], cw, args.timm_weight, args.threshold)
        spred = _combine(inat, sd["block_p"], sd["contrast_p"], cw, args.timm_weight, args.threshold)
        crop_rows.append((positive, cpred))
        stretch_rows.append((positive, spred))
        flips += cpred != spred
        n += 1

    if not n:
        raise SystemExit("no samples matched the report's names -- is this the dataset the report was built from?")
    cr, sr = _metrics(crop_rows), _metrics(stretch_rows)
    print(f"Samples: {n}  (threshold={args.threshold}, timm_weight={args.timm_weight}, contrast_weight={cw})")
    print(f"  center-crop (server):  recall={cr[0]:.3f} fpr={cr[1]:.3f} prec={cr[2]:.3f}")
    print(f"  stretch (old in-browser): recall={sr[0]:.3f} fpr={sr[1]:.3f} prec={sr[2]:.3f}")
    print(f"  verdict flips: {flips} / {n} ({100 * flips / n:.1f}%)")


if __name__ == "__main__":
    main()
