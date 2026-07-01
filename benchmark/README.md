# Benchmarks

Ready-to-run measurement scripts for the ImgEdge decode and inference paths. Run
them from the repository root with the project virtualenv active.

| Script | What it measures |
| --- | --- |
| [`bench_decode.py`](bench_decode.py) | Warm decode latency: in-process vs the subprocess pool vs the AppContainer pool (plus AppContainer cold-start). |
| [`bench_infer.py`](bench_infer.py) | Warm inference latency: per-voter forward cost and the 2-/3-/4-model profile totals (Fast / Balanced / Accurate / Maximum). |
| [`footprint.py`](footprint.py) | Resident RAM + private commit of the server and decode workers, and the parent with the full model ensemble loaded. |

These exercise the real `DecodePool` / `AppContainerPool`, so the numbers reflect
the shipped code paths (full IPC round-trip, the same `open_guarded` decode).

## Regression guards in CI

These same paths are guarded against regressions by
[`tests/test_perf_decode.py`](../tests/test_perf_decode.py) — relative/invariant
checks (warm-pool reuse, IPC overhead, the per-worker `OPENBLAS_NUM_THREADS=1`
cap) that tolerate CI runner noise. They run as the **Performance guards** CI job
and locally with `pytest -m perf`. Use the scripts below for actual numbers.

Fine-grained, **noise-free** deltas come from **CodSpeed** — the `test_*.py`
files in this folder are an instruction-count benchmark suite (decode, salience,
voting) run by the CodSpeed workflow (`pytest benchmark/ --codspeed`), which
comments per-benchmark changes on PRs.

## bench_decode.py

```pwsh
python benchmark/bench_decode.py
python benchmark/bench_decode.py --sizes 256,1024 --iters 50 --workers 2
```

Each row decodes the same JPEG and returns the real uint8 RGB array, so the pool
rows include the array copy back to the parent. AppContainer rows run on Windows
only (it falls back to just in-process + `DecodePool` elsewhere).

## bench_infer.py

```pwsh
python benchmark/bench_infer.py
python benchmark/bench_infer.py --iters 100 --threads 2
```

Times the **inference** path (not decode) on a seeded synthetic noise image — no
real image is created or shown. It prints each voter's forward cost, then the
cost of each **profile** (voter subset) so you can weigh speed against accuracy:

| Profile | Voters | Use |
| --- | --- | --- |
| Fast | iNat + timm | weak hardware; cheapest verdict |
| Balanced | + MobileCLIP | +open-vocabulary, modest cost |
| Accurate | + SigLIP | the `oi_split_sig` config (lowest web FPR) |
| Maximum | all four | belt-and-braces |

Profile rows force every voter to run (they report the cascade **worst case** — a
suspect image; clearly-allow images skip the deferred voters and are cheaper).
Install the extras you want to measure first:
`pip install -e ".[voters,siglip,mobileclip]"` and `imgedge-download-models`; an
absent voter's profiles print `unavailable`. Add the decode cost from
`bench_decode.py` for the full per-image budget.

### Simulating weak hardware

The benchmark prints its effective thread config, so constrained runs are
self-documenting. Cap threads in-process (all platforms):

```pwsh
python benchmark/bench_infer.py --threads 2
```

**Docker** is the most reproducible cross-platform cap (CPU **and** RAM):

```pwsh
# PowerShell uses ${PWD}; on bash/zsh use $PWD
docker run --rm --cpus=2 --memory=2g -v ${PWD}:/app -w /app python:3.13 bash -lc `
  "pip install -e '.[voters,siglip,mobileclip]' && imgedge-download-models && python benchmark/bench_infer.py"
```

Per-OS CPU pinning / throttling (each is OS-specific by design):

- **Linux** — pin cores with `taskset -c 0-1 python benchmark/bench_infer.py`, or
  cap CPU + RAM via cgroups: `systemd-run --scope -p CPUQuota=200% -p MemoryMax=2G python benchmark/bench_infer.py`.
- **Windows** — pin cores in PowerShell:
  `$p = Start-Process python -ArgumentList 'benchmark/bench_infer.py' -PassThru; $p.ProcessorAffinity = 0x3` (cores 0–1).
  Underclock: `powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX 50; powercfg /setactive SCHEME_CURRENT`.
- **macOS** — no built-in CPU pinning; use `--threads` or the Docker recipe above.

## footprint.py

```pwsh
python benchmark/footprint.py
```

Prints `working-set / private-commit` MB for the parent and each decode worker,
then the parent with both voters loaded. Windows only (it reads Win32 process
counters). numpy is imported lazily so the workers' `OPENBLAS_NUM_THREADS=1` cap
is measured faithfully.
