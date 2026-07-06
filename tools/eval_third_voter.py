# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Offline experiment: does adding a THIRD ImageNet voter improve recall?

The in-browser "Fast" ensemble is iNat + timm (mobilenetv3_large_100). This
measures whether adding a second, architecturally different ImageNet-1k
classifier as a third voter -- reusing the same arachnid-class voting as
`voters/timm_voter.py` -- lifts recall without spending the FPR budget, *before*
committing to bundling it.

It runs all three voters (iNat + timm + candidate) over the dataset in one pass
and folds the candidate's signed evidence into the in-browser combine
(`extension/inbrowser/ensemble.mjs` `combineEvidence`, salience deferred = 1.0),
then sweeps the threshold x candidate-weight grid. Candidate weight 0.0 is the
current 2-voter baseline, so each row's recall delta is the candidate's marginal
contribution. (iNat is re-run rather than read from an eval report because the
report's `records` are anonymised and not in dataset order, so there's no key to
reuse them.)

Needs the model (`imgedge-download-models`), the voter + eval deps
(`pip install -e ".[voters,eval]"`), and the encrypted eval dataset:

  # password via $IMGEDGE_EVAL_PASSWORD or an interactive prompt
  python tools/eval_third_voter.py dataset.eval.zip
  python tools/eval_third_voter.py dataset.eval.zip --model tf_efficientnetv2_b0 --sample-per-class 500

The candidate is any timm ImageNet-1k model whose class labels match the
arachnid BLOCK_TERMS (so a different architecture reuses the exact voting). A
CNN like `efficientnet_b0` is the safest first try; a transformer such as
`deit3_small_patch16_224` is more decorrelated but may run slower. Confirm the
checkpoint's licence on its Hugging Face model card before bundling -- timm's
own `*_in1k` recipes are Apache-2.0, but some ported weights carry their
upstream licence.

iNat dominates the runtime (~215 ms/image); use --sample-per-class for a quick
pass over a random subset.
"""

import argparse
import getpass
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
    ap.add_argument("--model", default="efficientnet_b0", help="candidate timm model (default: efficientnet_b0)")
    ap.add_argument("--timm-weight", type=float, default=0.5, help="weight of the existing timm voter (default 0.5)")
    ap.add_argument("--contrast-weight", type=float, default=0.0, help="look-alike contrast weight, both voters")
    ap.add_argument("--max-fpr", type=float, default=0.10, help="FPR budget for the recall-max point")
    ap.add_argument("--sample-per-class", type=int, help="score a random N per class for a faster pass")
    ap.add_argument("--seed", type=int, default=1234, help="random seed for --sample-per-class")
    ap.add_argument("--out", help="optional JSON path to dump the per-image scores")
    args = ap.parse_args()

    from eval_filter import _labeled_names, _Progress, _sample_names, iter_samples

    try:
        from imgedge.classifier.server import load_filter
        from imgedge.inat.inat_filter import open_guarded
        from imgedge.voters.inat_voter import InatVoter
        from imgedge.voters.timm_voter import TimmVoter
    except Exception as e:  # pragma: no cover - depends on optional extras
        raise SystemExit(f'deps missing ({e}). Install: pip install -e ".[voters,eval]"') from e

    inat_model = load_filter()
    if inat_model is None:
        raise SystemExit("no iNaturalist model found -- run: imgedge-download-models")
    inat, timm = InatVoter(inat_model), TimmVoter()
    voter = TimmVoter(model_name=args.model)  # the candidate 3rd voter
    info = f"{inat.name} + {timm.name} + candidate {voter.name}"
    print(f"Voters: {info} ({voter.matched} block / {voter.contrast_matched} contrast classes)")
    if not voter.matched:
        raise SystemExit(
            f"'{args.model}' matched 0 arachnid classes -- not an ImageNet-1k model? (labels vs BLOCK_TERMS)"
        )

    pw = os.environ.get("IMGEDGE_EVAL_PASSWORD")
    if pw is None and str(args.dataset).lower().endswith(".zip"):
        pw = getpass.getpass("Dataset password: ")
    only = _sample_names(args.dataset, pw, args.sample_per_class, args.seed) if args.sample_per_class else None
    total = len(only) if only is not None else sum(1 for _ in _labeled_names(args.dataset, pw))

    # Runs iNat + timm + candidate over each image (no eval report needed): the
    # report's `records` are anonymised and not in dataset order, so there's no
    # key to reuse them. iNat dominates the cost -- use --sample-per-class to
    # shorten a pass. Progress (count / rate / ETA) prints to stderr.
    scores, dumped, errors = [], [], 0
    prog = _Progress(total)
    for label, name, raw in iter_samples(args.dataset, pw, only):
        prog.tick()
        try:
            with open_guarded(raw) as img:
                inat_s = float(inat.score(img))
                td = timm.assess(img)[2]
                cd = voter.assess(img)[2]
        except Exception:
            errors += 1
            continue
        tb, tc = float(td["block_p"]), float(td["contrast_p"])
        cb, cc = float(cd["block_p"]), float(cd["contrast_p"])
        scores.append((label == "block", inat_s, tb, tc, cb, cc))
        if args.out is not None:
            dumped.append(
                {
                    "name": name,
                    "label": label,
                    "inat": inat_s,
                    "timm_block": tb,
                    "timm_contrast": tc,
                    "cand_block": cb,
                    "cand_contrast": cc,
                }
            )
    prog.close()

    matched = len(scores)
    if not matched:
        raise SystemExit("no images scored -- check the dataset path and password")
    n_pos = sum(1 for s in scores if s[0])
    print(f"Scored {matched} images ({n_pos} block / {matched - n_pos} allow); {errors} decode/infer errors\n")

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
