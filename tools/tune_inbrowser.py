# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Tune the in-browser (iNat + timm) ensemble parameters from saved eval reports.

The in-browser "Fast" ensemble is a 2-voter subset of the server ensemble, so
its optimal threshold / timm weight / contrast weight differ from the server's
full-ensemble tuning. Rather than re-run inference, this reconstructs the exact
in-browser combined score (extension/inbrowser/ensemble.mjs `combineEvidence`,
salience deferred = 1.0) from the per-image voter scores already captured in an
eval report's `records` array (tools/eval_filter.py), and sweeps parameters to
report recall / FPR / precision / F1.

  python tools/tune_inbrowser.py inat_split.json oi_split.json

Caveat: the report's timm/iNat scores use the server's PIL/timm preprocessing;
the extension resizes via canvas (best-effort parity), so live scores differ
slightly. This gives the ideal operating point to aim for, not an exact match.
"""

import argparse
import json
from pathlib import Path

# Grids to sweep.
TIMM_WEIGHTS = [0.0, 0.25, 0.5, 0.75, 1.0]
CONTRAST_WEIGHTS = [0.0, 0.25, 0.5]
THRESHOLDS = [round(0.01 * i, 2) for i in range(1, 71)]  # 0.01 .. 0.70
INAT_OVERRIDE = 0.9


def load_records(paths):
    recs = []
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        for r in data.get("records", []):
            inat = r.get("inat")
            tb = r.get("timm_block")
            tc = r.get("timm_contrast")
            if inat is None or tb is None or tc is None:
                continue  # need both voters
            recs.append((r["label"] == "block", float(inat), float(tb), float(tc)))
    return recs


def combined(inat, tb, tc, tw, cw):
    """Mirror ensemble.mjs combineEvidence (salience = 1.0), returning (score, override)."""
    timm_ev = tb - cw * tc
    pos = inat if inat > 0 else 0.0  # iNat weight 1.0, evidence = score >= 0
    neg = 0.0
    if tw > 0.0:
        if timm_ev > 0:
            pos += tw * timm_ev
        elif timm_ev < 0:
            neg += tw * timm_ev
    score = max(0.0, min(1.0, pos + neg))
    override = inat >= INAT_OVERRIDE
    if override:
        score = max(score, inat)
    return score, override


def metrics_at(recs, tw, cw, thr):
    tp = fp = tn = fn = 0
    for positive, inat, tb, tc in recs:
        score, override = combined(inat, tb, tc, tw, cw)
        pred = override or score >= thr
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
    f1 = (2 * prec * recall / (prec + recall)) if (prec + recall) else 0.0
    return recall, fpr, prec, f1


def best_for(recs, tw, cw, max_fpr):
    """Return (best-F1 point, best recall@fpr<=max_fpr point)."""
    best_f1 = (0.0, None)  # (f1, (thr,recall,fpr,prec))
    best_rec = (-1.0, None)  # (recall, (thr,recall,fpr,prec))
    for thr in THRESHOLDS:
        recall, fpr, prec, f1 = metrics_at(recs, tw, cw, thr)
        if f1 > best_f1[0]:
            best_f1 = (f1, (thr, recall, fpr, prec))
        if fpr <= max_fpr and recall > best_rec[0]:
            best_rec = (recall, (thr, recall, fpr, prec))
    return best_f1[1], best_rec[1]


def main():
    ap = argparse.ArgumentParser(description="Tune the in-browser ensemble from eval reports.")
    ap.add_argument("reports", nargs="+", help="eval report JSON files (with a `records` array)")
    ap.add_argument("--max-fpr", type=float, default=0.10, help="FPR budget for the recall-max point")
    args = ap.parse_args()

    recs = load_records(args.reports)
    pos = sum(1 for r in recs if r[0])
    print(f"Loaded {len(recs)} records ({pos} block / {len(recs) - pos} allow) from {', '.join(args.reports)}\n")

    # Current in-browser defaults, for reference.
    r0 = metrics_at(recs, 0.5, 0.0, 0.5)
    print(
        f"CURRENT (timm_w=0.5, cw=0.0, thr=0.50): recall={r0[0]:.3f} fpr={r0[1]:.3f} prec={r0[2]:.3f} f1={r0[3]:.3f}\n"
    )

    print(
        f"{'timm_w':>6} {'cw':>4} | {'best-F1: thr':>12} {'rec':>5} {'fpr':>5} {'prec':>5} {'f1':>5} | "
        f"{'rec@fpr<=' + str(args.max_fpr):>14} {'thr':>4} {'fpr':>5}"
    )
    for tw in TIMM_WEIGHTS:
        for cw in CONTRAST_WEIGHTS if tw > 0 else [0.0]:
            f1pt, recpt = best_for(recs, tw, cw, args.max_fpr)
            thr, rec, fpr, prec = f1pt
            print(
                f"{tw:>6.2f} {cw:>4.2f} | thr={thr:>4.2f} rec={rec:.3f} fpr={fpr:.3f} prec={prec:.3f}"
                + (
                    f"  ||  rec@fpr<={args.max_fpr}: {recpt[1]:.3f} @thr={recpt[0]:.2f} (fpr={recpt[2]:.3f})"
                    if recpt
                    else "  ||  (none within FPR budget)"
                )
            )


if __name__ == "__main__":
    main()
