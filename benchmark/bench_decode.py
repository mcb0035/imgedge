"""Warm decode latency: in-process vs subprocess pool vs AppContainer.

Run from the repo root with the project venv:
    python benchmark/bench_decode.py
    python benchmark/bench_decode.py --sizes 256,1024 --iters 50 --workers 2

Each row decodes the SAME JPEG and returns the real uint8 RGB array, so the pool
rows include the full IPC round-trip (the decoded array copied back to the
parent), not just a fire-and-forget call. AppContainer rows run on Windows only.
"""
import argparse
import io
import statistics
import sys
import time


def _jpeg(side):
    import numpy as np
    from PIL import Image
    buf = io.BytesIO()
    arr = (np.random.default_rng(0).random((side, side, 3)) * 255).astype("uint8")
    Image.fromarray(arr).save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _bench(fn, raw, iters, warm=3):
    ts = []
    for i in range(iters + warm):
        t = time.perf_counter()
        fn(raw)
        if i >= warm:
            ts.append((time.perf_counter() - t) * 1000)
    ts.sort()
    return statistics.median(ts), ts[min(len(ts) - 1, int(len(ts) * 0.95))], ts[0]


def _row(label, fn, raw, iters):
    med, p95, lo = _bench(fn, raw, iters)
    print(f"  {label:<22} median={med:7.2f}  p95={p95:7.2f}  min={lo:7.2f} ms")


def main():
    parser = argparse.ArgumentParser(description="warm decode latency benchmark")
    parser.add_argument("--sizes", default="256,1280", help="comma-separated square sizes")
    parser.add_argument("--iters", type=int, default=30)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    sizes = [int(s) for s in args.sizes.split(",")]

    from imgedge.classifier.decode_pool import DecodePool, _decode

    def inproc(raw):
        return _decode(raw, 1024)

    print(f"warm decode latency  (iters={args.iters}, workers={args.workers})\n")
    dp = DecodePool(workers=args.workers)
    dp.decode(_jpeg(64))  # warm

    ac = None
    if sys.platform == "win32":
        from imgedge.classifier.ac_pool import AppContainerPool
        t0 = time.perf_counter()
        ac = AppContainerPool(workers=args.workers)
        ac.decode(_jpeg(64))
        print(f"AppContainer cold spawn -> warm-ready: "
              f"{(time.perf_counter() - t0) * 1000:.0f} ms (one-time)\n")

    try:
        for side in sizes:
            raw = _jpeg(side)
            print(f"{side}x{side} JPEG:")
            _row("in-process", inproc, raw, args.iters)
            _row("DecodePool (warm)", dp.decode, raw, args.iters)
            if ac is not None:
                _row("AppContainer (warm)", ac.decode, raw, args.iters)
            print()
    finally:
        dp.close()
        if ac is not None:
            ac.close()


if __name__ == "__main__":
    main()
