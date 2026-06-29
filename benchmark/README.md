# Benchmarks

Ready-to-run measurement scripts for the ImgEdge decode path. Run them from the
repository root with the project virtualenv active.

| Script | What it measures |
| --- | --- |
| [`bench_decode.py`](bench_decode.py) | Warm decode latency: in-process vs the subprocess pool vs the AppContainer pool (plus AppContainer cold-start). |
| [`footprint.py`](footprint.py) | Resident RAM + private commit of the server and decode workers, and the parent with the full model ensemble loaded. |

These exercise the real `DecodePool` / `AppContainerPool`, so the numbers reflect
the shipped code paths (full IPC round-trip, the same `open_guarded` decode).

## Regression guards in CI

These same paths are guarded against regressions by
[`tests/test_perf_decode.py`](../tests/test_perf_decode.py) — relative/invariant
checks (warm-pool reuse, IPC overhead, the per-worker `OPENBLAS_NUM_THREADS=1`
cap) that tolerate CI runner noise. They run as the **Performance guards** CI job
and locally with `pytest -m perf`. Use the scripts below for actual numbers.

## bench_decode.py

```pwsh
python benchmark/bench_decode.py
python benchmark/bench_decode.py --sizes 256,1024 --iters 50 --workers 2
```

Each row decodes the same JPEG and returns the real uint8 RGB array, so the pool
rows include the array copy back to the parent. AppContainer rows run on Windows
only (it falls back to just in-process + `DecodePool` elsewhere).

## footprint.py

```pwsh
python benchmark/footprint.py
```

Prints `working-set / private-commit` MB for the parent and each decode worker,
then the parent with both voters loaded. Windows only (it reads Win32 process
counters). numpy is imported lazily so the workers' `OPENBLAS_NUM_THREADS=1` cap
is measured faithfully.
