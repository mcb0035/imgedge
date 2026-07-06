# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Offline experiment: does adding a THIRD ImageNet voter improve recall?

The in-browser "Fast" ensemble is iNat + timm (mobilenetv3_large_100). This
measures whether adding a second, architecturally different ImageNet-1k
classifier as a third voter -- reusing the same arachnid-class voting as
`voters/timm_voter.py` -- lifts recall without spending the FPR budget, *before*
committing to bundling it.

The iNat and timm scores are held fixed (read from an eval report); only the
candidate model is run over the dataset. Its signed evidence is folded into the
in-browser combine (`extension/inbrowser/ensemble.mjs` `combineEvidence`,
salience deferred = 1.0) and the threshold x candidate-weight grid is swept.
Candidate weight 0.0 is the current 2-voter baseline, so each row's recall delta
is the candidate's marginal contribution.

Needs the voter deps (timm + torch) and the encrypted eval dataset:

  # password via $IMGEDGE_EVAL_PASSWORD or an interactive prompt
  python tools/eval_third_voter.py dataset.eval.zip --report inat_split.json
  python tools/eval_third_voter.py dataset.eval.zip --report inat_split.json --model tf_efficientnetv2_b0

The candidate is any timm ImageNet-1k model whose class labels match the
arachnid BLOCK_TERMS (so a different architecture reuses the exact voting). A
CNN like `efficientnet_b0` is the safest first try; a transformer such as
`deit3_small_patch16_224` is more decorrelated but may run slower. Confirm the
checkpoint's licence on its Hugging Face model card before bundling -- timm's
own `*_in1k` recipes are Apache-2.0, but some ported weights carry their
upstream licence.
"""

import argparse
import getpass
import io
import json
import os
from pathlib import Path

INAT_OVERRIDE = 0.9
CAND_WEIGHTS = [0.0, 0.25, 0.5, 0.75, 1.0]
THRESHOLDS = [round(0.01 * i, 2) for i in range(1, 71)]  # 0.01 .. 0.70


def combine(inat, tb, tc, cb, cc, tw, cw, w3, thr):
    """Mirror the in-browser combineEvidence for iNat + timm + candidate
    (salience deferred = 1.0); return the block decision at `thr`. `cw` is the
    look-alike contrast weight applied to both ImageNet voters."""
    pos = inat if inat > 0 else 0.0
    neg = 0.0
    for evidence, weight in ((tb - cw * tc, tw), (cb - cw * cc, w3)):
        if weight <= 0.0:
            continue
        if evidence > 0:
            pos += weight * evidence
        elif evidence < 0:
            neg += weight * evidence
    score = max(0.0, min(1.0, pos + neg))
    if inat >= INAT_OVERRIDE:
        score = max(score, inat)
    return bool(inat >= INAT_OVERRIDE or score >= thr)


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


def best_recall(scores, tw, cw, w3, max_fpr):
    """Best (recall, thr, fpr, prec) with fpr <= max_fpr over the threshold grid."""
    best = (-1.0, None, None, None)
    for thr in THRESHOLDS:
        rows = [(pos, combine(inat, tb, tc, cb, cc, tw, cw, w3, thr)) for (pos, inat, tb, tc, cb, cc) in scores]
        recall, fpr, prec = _metrics(rows)
        if fpr <= max_fpr and recall > best[0]:
            best = (recall, thr, fpr, prec)
    return best


def main():
    ap = argparse.ArgumentParser(description="Measure whether a third ImageNet voter improves recall.")
    ap.add_argument("dataset", help="encrypted .eval.zip or a block/ + allow/ directory")
    ap.add_argument("--report", required=True, help="eval report JSON (source of the fixed iNat + timm scores)")
    ap.add_argument("--model", default="efficientnet_b0", help="candidate timm model (default: efficientnet_b0)")
    ap.add_argument("--timm-weight", type=float, default=0.5, help="weight of the existing timm voter (default 0.5)")
    ap.add_argument("--contrast-weight", type=float, default=0.0, help="look-alike contrast weight, both voters")
    ap.add_argument("--max-fpr", type=float, default=0.10, help="FPR budget for the recall-max point")
    ap.add_argument("--out", help="optional JSON path to dump the per-image scores for reuse")
    args = ap.parse_args()

    from eval_filter import iter_samples

    try:
        from PIL import Image

        from imgedge.voters.timm_voter import TimmVoter
    except Exception as e:  # pragma: no cover - depends on optional extras
        raise SystemExit(f'deps missing ({e}). Install: pip install -e ".[voters]"') from e

    rep = json.loads(Path(args.report).read_text(encoding="utf-8"))
    fixed = {}
    for r in rep.get("records", []):
        if r.get("inat") is not None and r.get("timm_block") is not None and r.get("timm_contrast") is not None:
            fixed[r["name"]] = (float(r["inat"]), float(r["timm_block"]), float(r["timm_contrast"]))
    if not fixed:
        raise SystemExit(f"{args.report} has no records with iNat + timm scores (need its `records` array)")

    voter = TimmVoter(model_name=args.model)
    print(f"Candidate: {voter.name} on {voter.provider} -- {voter.matched} block / {voter.contrast_matched} contrast")
    if not voter.matched:
        raise SystemExit(
            f"'{args.model}' matched 0 arachnid classes -- not an ImageNet-1k model? (labels vs BLOCK_TERMS)"
        )

    pw = os.environ.get("IMGEDGE_EVAL_PASSWORD")
    if pw is None and str(args.dataset).lower().endswith(".zip"):
        pw = getpass.getpass("Dataset password: ")

    scores, dumped, skipped = [], [], 0
    for label, name, raw in iter_samples(args.dataset, pw):
        f = fixed.get(name)
        if f is None:
            skipped += 1
            continue
        inat, tb, tc = f
        try:
            img = Image.open(io.BytesIO(raw))
            d = voter.assess(img)[2]
        except Exception:
            skipped += 1
            continue
        cb, cc = float(d["block_p"]), float(d["contrast_p"])
        scores.append((label == "block", inat, tb, tc, cb, cc))
        if args.out is not None:
            dumped.append(
                {
                    "name": name,
                    "label": label,
                    "inat": inat,
                    "timm_block": tb,
                    "timm_contrast": tc,
                    "cand_block": cb,
                    "cand_contrast": cc,
                }
            )

    matched = len(scores)
    if not matched:
        raise SystemExit("no dataset images matched the report's names -- is this the report's own dataset?")
    n_pos = sum(1 for s in scores if s[0])
    print(f"Scored {matched} images ({n_pos} block / {matched - n_pos} allow); {skipped} skipped\n")

    tw, cw, mf = args.timm_weight, args.contrast_weight, args.max_fpr
    br, bthr, bfpr, bprec = best_recall(scores, tw, cw, 0.0, mf)  # cand weight 0 == current 2-voter combo
    print(f"Baseline iNat + timm (cand weight 0): recall={br:.3f} @thr={bthr:.2f} fpr={bfpr:.3f} prec={bprec:.3f}")
    print(f"\nAdding {voter.name} as a 3rd voter (timm_w={tw}, contrast_w={cw}, salience=1.0):")
    print(f"{'cand_w':>6} | {'thr':>4} {'recall':>6} {'fpr':>5} {'prec':>5} | Δrecall@fpr<={mf}")
    for w3 in CAND_WEIGHTS:
        rec, thr, fpr, prec = best_recall(scores, tw, cw, w3, mf)
        tag = "(baseline)" if w3 == 0.0 else f"{rec - br:+.3f}"
        print(f"{w3:>6.2f} | {thr:>4.2f} {rec:>6.3f} {fpr:>5.3f} {prec:>5.3f} | {tag}")

    if args.out is not None:
        payload = {
            "model": voter.name,
            "n": matched,
            "timm_weight": tw,
            "contrast_weight": cw,
            "records": dumped,
        }
        Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote per-image scores to {args.out}")


if __name__ == "__main__":
    main()
