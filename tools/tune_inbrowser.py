# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Tune the in-browser (iNat + timm [+ optional deit3]) ensemble from eval reports.

The in-browser "Fast" ensemble is a small subset of the server ensemble, so
its optimal threshold / timm weight / contrast weight differ from the server's
full-ensemble tuning. Rather than re-run inference, this reconstructs the exact
in-browser combined score (extension/inbrowser/ensemble.mjs `combineEvidence`,
salience deferred = 1.0) from the per-image voter scores already captured in an
eval report's `records` array (tools/eval_filter.py), and sweeps parameters to
report recall / FPR / precision / F1.

  python tools/tune_inbrowser.py inat_split.json oi_split.json

When the reports also carry deit3 `cand_block` scores (from
`tools/eval_third_voter.py --out`), a third-voter weight sweep is added:

  python tools/tune_inbrowser.py reports/deit3_small.json reports/deit3_oi.json

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
# deit3 third-voter weights to sweep (only used when a report carries deit3
# `cand_block` scores; mirrors deit3_web.json's contrast_weight = 0.0).
DEIT3_WEIGHTS = [0.0, 0.25, 0.5, 0.75, 1.0]
THRESHOLDS = [round(0.01 * i, 2) for i in range(1, 71)]  # 0.01 .. 0.70
INAT_OVERRIDE = 0.9


def load_records(paths):
    recs = []
    has_deit3 = False
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        for r in data.get("records", []):
            inat = r.get("inat")
            tb = r.get("timm_block")
            tc = r.get("timm_contrast")
            if inat is None or tb is None or tc is None:
                continue  # need both voters
            cb = r.get("cand_block")  # deit3 third voter, when present
            cc = r.get("cand_contrast")
            if cb is not None:
                has_deit3 = True
            mult = r.get("mult")
            recs.append(
                (
                    r["label"] == "block",
                    float(inat),
                    float(tb),
                    float(tc),
                    float(cb) if cb is not None else 0.0,
                    float(cc) if cc is not None else 0.0,
                    float(mult) if mult is not None else 1.0,
                )
            )
    return recs, has_deit3


def _salience_mult(mult, mode):
    if mode == "boost":
        return max(1.0, mult)  # server behaviour: salience never suppresses
    if mode == "full":
        return mult  # also allow suppression below 1.0
    return 1.0  # "off": current in-browser (salience deferred)


def combined(inat, tb, tc, cb, cc, tw, cw, dw=0.0, dcw=0.0, mult=1.0, sal="off"):
    """Mirror ensemble.mjs combineEvidence, returning (score, override). `sal`
    selects the salience strategy applied to the positive evidence; `dw` adds the
    optional deit3 third voter (evidence cb - dcw*cc)."""
    pos = inat if inat > 0 else 0.0  # iNat weight 1.0, evidence = score >= 0
    neg = 0.0
    for w, ev in ((tw, tb - cw * tc), (dw, cb - dcw * cc)):
        if w > 0.0:
            if ev > 0:
                pos += w * ev
            elif ev < 0:
                neg += w * ev
    score = max(0.0, min(1.0, pos * _salience_mult(mult, sal) + neg))
    override = inat >= INAT_OVERRIDE
    if override:
        score = max(score, inat)
    return score, override


def metrics_at(recs, tw, cw, thr, sal="off", dw=0.0, dcw=0.0):
    tp = fp = tn = fn = 0
    for positive, inat, tb, tc, cb, cc, mult in recs:
        score, override = combined(inat, tb, tc, cb, cc, tw, cw, dw, dcw, mult, sal)
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


def best_for(recs, tw, cw, max_fpr, sal="off", dw=0.0, dcw=0.0):
    """Return (best-F1 point, best recall@fpr<=max_fpr point)."""
    best_f1 = (0.0, None)  # (f1, (thr,recall,fpr,prec))
    best_rec = (-1.0, None)  # (recall, (thr,recall,fpr,prec))
    for thr in THRESHOLDS:
        recall, fpr, prec, f1 = metrics_at(recs, tw, cw, thr, sal, dw, dcw)
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

    recs, has_deit3 = load_records(args.reports)
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

    print("\nSalience at timm_w=0.5, cw=0.0 (does applying image salience help the 2-model combo?):")
    print(f"{'strategy':>10} | best-F1: thr  rec   fpr   prec  ||  rec@fpr<={args.max_fpr}")
    for sal, label in (("off", "off (1.0)"), ("boost", "boost-only"), ("full", "full")):
        f1pt, recpt = best_for(recs, 0.5, 0.0, args.max_fpr, sal)
        thr, rec, fpr, prec = f1pt
        print(
            f"{label:>10} | thr={thr:>4.2f} rec={rec:.3f} fpr={fpr:.3f} prec={prec:.3f}"
            + (f"  ||  {recpt[1]:.3f} @thr={recpt[0]:.2f}" if recpt else "  ||  (none)")
        )

    if has_deit3:
        print("\nWith the deit3 third voter (timm_w=0.5, cw=0.0, deit3 cw=0.0):")
        print(f"{'deit3_w':>7} | {'best-F1: thr':>12} {'rec':>5} {'fpr':>5} {'prec':>5} | rec@fpr<={args.max_fpr}")
        for dw in DEIT3_WEIGHTS:
            f1pt, recpt = best_for(recs, 0.5, 0.0, args.max_fpr, "off", dw, 0.0)
            thr, rec, fpr, prec = f1pt
            tail = (
                f"  ||  {recpt[1]:.3f} @thr={recpt[0]:.2f} (fpr={recpt[2]:.3f})"
                if recpt
                else "  ||  (none within budget)"
            )
            print(f"{dw:>7.2f} | thr={thr:>4.2f} rec={rec:.3f} fpr={fpr:.3f} prec={prec:.3f}{tail}")


if __name__ == "__main__":
    main()
