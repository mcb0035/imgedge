# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Measure how much the in-browser timm resize (a straight 224x224 stretch)
changes verdicts vs. the server's Resize + CenterCrop, on the 2-model combo.

The iNat score is computed once per image and held fixed across both timm
variants, and only the timm voter's transform changes -- its normal center-crop
vs. a stretch -- so the difference is purely the resize. Reports recall / FPR
under each and how many verdicts flip. Needs the model
(`imgedge-download-models`), the voter + eval deps
(`pip install -e ".[voters,eval]"`), and the encrypted eval dataset:

  # password via $IMGEDGE_EVAL_PASSWORD or an interactive prompt
  python tools/measure_resize.py dataset.eval.zip
  python tools/measure_resize.py dataset.eval.zip --sample-per-class 500

iNat dominates the runtime (~215 ms/image); use --sample-per-class for a quick
pass over a random subset.
"""

import argparse
import getpass
import os


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
    ap.add_argument("--threshold", type=float, default=0.15)
    ap.add_argument("--timm-weight", type=float, default=0.5)
    ap.add_argument("--sample-per-class", type=int, help="score a random N per class for a faster pass")
    ap.add_argument("--seed", type=int, default=1234, help="random seed for --sample-per-class")
    args = ap.parse_args()

    from eval_filter import _sample_names, iter_samples

    try:
        from timm.data import resolve_model_data_config
        from torchvision import transforms as T

        from imgedge.classifier.server import load_filter
        from imgedge.inat.inat_filter import open_guarded
        from imgedge.voters.inat_voter import InatVoter
        from imgedge.voters.timm_voter import TimmVoter
    except Exception as e:
        raise SystemExit(f'deps missing ({e}). Install: pip install -e ".[voters,eval]"') from e

    inat_model = load_filter()
    if inat_model is None:
        raise SystemExit("no iNaturalist model found -- run: imgedge-download-models")
    inat = InatVoter(inat_model)

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
    only = _sample_names(args.dataset, pw, args.sample_per_class, args.seed) if args.sample_per_class else None

    crop_rows, stretch_rows, flips, n, errors = [], [], 0, 0, 0
    for label, _name, raw in iter_samples(args.dataset, pw, only):
        try:
            with open_guarded(raw) as img:
                inat_s = float(inat.score(img))  # computed once, held fixed for both timm variants
                voter.transform = crop_transform
                cd = voter.assess(img)[2]
                voter.transform = stretch_transform
                sd = voter.assess(img)[2]
        except Exception:
            errors += 1
            continue
        positive = label == "block"
        cpred = _combine(inat_s, cd["block_p"], cd["contrast_p"], cw, args.timm_weight, args.threshold)
        spred = _combine(inat_s, sd["block_p"], sd["contrast_p"], cw, args.timm_weight, args.threshold)
        crop_rows.append((positive, cpred))
        stretch_rows.append((positive, spred))
        flips += cpred != spred
        n += 1

    if not n:
        raise SystemExit("no images scored -- check the dataset path and password")
    cr, sr = _metrics(crop_rows), _metrics(stretch_rows)
    print(f"Samples: {n} ({errors} errors)  threshold={args.threshold}  timm_weight={args.timm_weight}  cw={cw}")
    print(f"  center-crop (server):  recall={cr[0]:.3f} fpr={cr[1]:.3f} prec={cr[2]:.3f}")
    print(f"  stretch (old in-browser): recall={sr[0]:.3f} fpr={sr[1]:.3f} prec={sr[2]:.3f}")
    print(f"  verdict flips: {flips} / {n} ({100 * flips / n:.1f}%)")


if __name__ == "__main__":
    main()
