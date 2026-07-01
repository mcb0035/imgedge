"""Warm inference latency: per-voter cost and 2-/3-/4-model profile totals.

Times the ensemble INFERENCE path (not decode -- see bench_decode.py) on a fixed
synthetic image, so you can measure the speed/accuracy trade-off of each voter
profile and how it degrades under constrained resources:

    python benchmark/bench_infer.py
    python benchmark/bench_infer.py --iters 100 --threads 2

Simulate weak hardware by constraining CPU/RAM externally (see benchmark/README.md):
    Linux  : taskset -c 0-1 python benchmark/bench_infer.py           # 2 cores
             podman run --cpus=2 --memory=2g <img> python benchmark/bench_infer.py  # or docker
    Windows: $p = Start-Process python 'benchmark/bench_infer.py' -PassThru; $p.ProcessorAffinity = 0x3
             powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX 50  # underclock

Needs the model (`imgedge-download-models`) and whichever voter extras you want to
measure (`pip install -e ".[voters,siglip,mobileclip]"`). The input is a seeded
synthetic noise image -- no real image is ever created, shown, or written.
Dev-only; never part of the shipped extension.
"""

import argparse
import os
import statistics
import sys
import time


def _synthetic(side):
    """A deterministic RGB noise image (seeded), so runs are comparable."""
    import numpy as np
    from PIL import Image

    arr = (np.random.default_rng(0).random((side, side, 3)) * 255).astype("uint8")
    return Image.fromarray(arr)


def _measure(fn, iters, warm):
    """Return p50/p90/p95/mean (ms) for `fn`, discarding `warm` warm-up calls."""
    ts = []
    for i in range(iters + warm):
        t = time.perf_counter()
        fn()
        if i >= warm:
            ts.append((time.perf_counter() - t) * 1000)
    ts.sort()
    n = len(ts)
    return {
        "p50": round(statistics.median(ts), 2),
        "p90": round(ts[min(n - 1, int(0.90 * n))], 2),
        "p95": round(ts[min(n - 1, int(0.95 * n))], 2),
        "mean": round(statistics.fmean(ts), 2),
    }


def _row(label, s):
    print(f"  {label:<32} p50={s['p50']:7.2f}  p90={s['p90']:7.2f}  p95={s['p95']:7.2f}  mean={s['mean']:7.2f} ms")


def main():
    p = argparse.ArgumentParser(description="warm ensemble inference latency benchmark")
    p.add_argument("--iters", type=int, default=50)
    p.add_argument("--warmup", type=int, default=5)
    p.add_argument("--size", type=int, default=384, help="synthetic image side in px")
    p.add_argument("--threads", type=int, default=None, help="cap CPU threads (OMP/OpenBLAS/MKL/torch)")
    args = p.parse_args()

    # Thread caps must be set before the numeric libraries initialise.
    if args.threads:
        for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            os.environ[var] = str(args.threads)

    # Enable every voter BEFORE importing the server: it snapshots the enable
    # flags into module constants at import. Voters whose extras aren't installed
    # are skipped by load_ensemble, so we measure whatever is available.
    os.environ.setdefault("IMGEDGE_SIGLIP", "1")
    os.environ.setdefault("IMGEDGE_MOBILECLIP", "1")

    from imgedge.classifier.server import load_ensemble
    from imgedge.voters.base import VoteEnsemble

    if args.threads:
        try:
            import torch

            torch.set_num_threads(args.threads)
        except ImportError:
            pass

    ens = load_ensemble()
    if ens is None:
        raise SystemExit("No ensemble available -- run `imgedge-download-models` first.")

    img = _synthetic(args.size)
    ens.classify(img)  # warm: trigger every voter's lazy model load

    by_name = {v.name.split(":", 1)[0]: v for v in ens.voters}
    torch_threads = sys.modules["torch"].get_num_threads() if "torch" in sys.modules else None
    print(f"Ensemble inference latency  (iters={args.iters}, size={args.size}px)")
    print(f"  loaded voters : {ens.names}")
    print(
        f"  threads       : OMP={os.environ.get('OMP_NUM_THREADS')} "
        f"OpenBLAS={os.environ.get('OPENBLAS_NUM_THREADS')} torch={torch_threads}\n"
    )

    print("Per-voter (one forward each; no cascade, no decode):")
    for v in ens.voters:
        _row(v.name, _measure(lambda v=v: v.assess(img), args.iters, args.warmup))

    profiles = [
        ("Fast (iNat + timm)", ["inat", "timm"]),
        ("Balanced (+ MobileCLIP)", ["inat", "timm", "mobileclip"]),
        ("Accurate (+ SigLIP)", ["inat", "timm", "siglip"]),
        ("Maximum (all)", ["inat", "timm", "siglip", "mobileclip"]),
    ]
    # threshold=2.0 keeps every image inside the cascade band, so the deferred
    # (SigLIP/MobileCLIP) voters always run -- we report each profile's worst
    # case (a suspect image), not the cheaper clear-allow cascade skip.
    print("\nProfile decision cost (full classify; all voters run, no decode):")
    for label, names in profiles:
        if not all(n in by_name for n in names):
            print(f"  {label:<32} (unavailable -- voter/extra not installed)")
            continue
        sub = VoteEnsemble(
            [by_name[n] for n in names],
            policy=ens.policy,
            threshold=2.0,
            inat_override=ens.inat_override,
            gate=ens.gate,
        )
        sub.inat = by_name.get("inat")
        _row(label, _measure(lambda sub=sub: sub.classify(img), args.iters, args.warmup))

    print("\nNote: add image decode (see bench_decode.py) for the full per-image cost.")


if __name__ == "__main__":
    main()
