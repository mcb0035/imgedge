# Evaluating & profiling the filter

[`tools/eval_filter.py`](../tools/eval_filter.py) runs the **real** classification
ensemble over a labelled dataset and reports quality (recall / false‑positive
rate) **and** decision latency — **without ever displaying, extracting, or
writing an image**. The dataset is read straight from an AES‑encrypted zip and
only per‑file *scores* (numbers) come out, so you can measure the arachnid filter
against arachnid images without being shown one.

- **Requirements:** the model (`imgedge-download-models`) and, for encrypted
  datasets, the eval extra (`pip install -e ".[eval]"`). The optional voters need
  their own extras (below). Dev‑only — never shipped in the extension.
- **Dataset layout** (paths inside the zip, or subfolders of a plain dir):
  `block/…` = images that *should* be blocked (positives), `allow/…` = images
  that should *not* (negatives).

> Commands below are shown for PowerShell. On bash/zsh set an environment
> variable with `export VAR=value` and clear it with `unset VAR`; everything
> else is identical.

## 1. Get a dataset

Build one without ever opening an image (pick one):

```powershell
python -m tools.eval_filter build-synthetic dataset.eval.zip   # procedural shapes, no real images
python -m tools.eval_filter build-urls urls.txt dataset.eval.zip  # a trusted "label,url" list
python -m tools.eval_filter build-dir ./eval-raw dataset.eval.zip # encrypt a folder, then delete it
```

`build-synthetic` needs no real imagery, so it's the safe way to try the tool and
to profile latency. Each writes an AES‑256 zip; set the password once per shell
with `$env:IMGEDGE_EVAL_PASSWORD="…"` (or answer the no‑echo prompt).

## 2. Choose the ensemble (how many models)

The base ensemble is **iNaturalist + timm** (2 models). The two open‑vocabulary
voters are opt‑in, so you select the configuration you want to measure:

| Config | Models | Command |
| --- | --- | --- |
| base | iNat + timm | *(no flag)* — needs `.[voters]` |
| 3-model | base + SigLIP | `--siglip` — needs `.[siglip]` |
| 3-model | base + MobileCLIP | `--mobileclip` — needs `.[mobileclip]` |
| 4-model | base + SigLIP + MobileCLIP | `--siglip --mobileclip` |

The flags are authoritative: the harness pins `IMGEDGE_SIGLIP` /
`IMGEDGE_MOBILECLIP` per run, so an omitted voter stays off regardless of your
shell or the server's load-if-installed default. Their fine-tuning knobs
(`IMGEDGE_SIGLIP_WEIGHT`, `IMGEDGE_SIGLIP_GATE`, `IMGEDGE_THRESHOLD`, …) stay as
environment variables — see the [configuration reference](configuration.md).

## 3. Run an eval

```powershell
python -m tools.eval_filter eval dataset.eval.zip --siglip --report out.json   # -> reports/out.json
```

Useful flags: `--siglip` / `--mobileclip` (pick the voters, above), `--report
<json>` (full machine-readable results; a bare name is written under `reports/`,
kept out of the repo root and gitignored), `--sample-per-class N` (+ `--seed`,
score a random N per class for a faster pass), `--threshold` / `--salience`
(override the operating point), `--threads N` (cap CPU threads for the models --
often faster on many-core boxes), `--no-sweep` (skip the threshold / salience
sweeps).

A progress meter (count, rate, ETA) prints to `stderr` during the run — useful
for the full sets, which take a while — and never touches the `--report` JSON;
add `--no-progress` to silence it.

**Scale & run time.** Every image is decoded and scored through the full
ensemble — a few hundred ms each on CPU, dominated by the iNaturalist model
(~215 ms; SigLIP ~70 ms, MobileCLIP ~60 ms, timm ~20 ms per image) — so full
runs are long. Reference timings (CPU; a ~10,000-image web set = 79 arachnids +
10,000 web negatives, and a ~3,500-image recall set at `--sample-per-class 2000`):

| Set | Config | Images | Time |
| --- | --- | --- | --- |
| web (FPR) | SigLIP (3-model) | 10,079 | ~54 min |
| web (FPR) | SigLIP + MobileCLIP (4-model) | 10,079 | ~1 h 03 min |
| recall | 4-model, `--sample-per-class 2000` | 3,530 | ~19 min |

Use `--sample-per-class N` to shorten a pass, and watch the progress meter's ETA;
the `latency` block reports the exact per-image cost for your hardware.

## 4. Read the quality results

The terminal output and the `--report` JSON both contain:

- **Operating point** — at the shipping threshold: `recall` (fraction of
  arachnids caught — the number that matters most for a phobia filter), `fpr`
  (fraction of `allow` images wrongly blocked), `precision`, `f1`.
- **`threshold_sweep`** — recall / FPR / precision at thresholds 0.05 → 0.90, so
  you can pick the trade‑off you want (higher threshold ⇒ fewer false positives,
  lower recall).
- **`salience_variants`** — `baseline` vs `off` vs `boost_only` salience
  weighting, computed analytically from each record (no re‑inference).

Good looks like **high recall at low FPR**; use the sweep to see where recall
falls off as you tighten the threshold.

## 5. Profile decision latency (2‑ vs 3‑ vs 4‑model)

Every eval also times the ensemble. The report's `latency` block (and a matching
terminal section) has two parts:

```jsonc
"latency": {
  // total time to classify ONE image (decode + every active voter), in ms
  "decision_ms":  { "n": 3530, "mean": 41.2, "p50": 12.8, "p90": 118.4, "p95": 132.7, "max": 900.1 },
  // each voter's OWN inference cost, over the images where it actually ran
  "per_voter_ms": {
    "inat:arachnida":              { "n": 3530, "p50": 3.1,  "... ": "..." },
    "timm:mobilenetv3_large_100":  { "n": 3530, "p50": 5.4,  "... ": "..." },
    "siglip:siglip2-base-patch16-224": { "n": 806, "p50": 95.0, "... ": "..." },
    "mobileclip:MobileCLIP2-S0":   { "n": 806, "p50": 22.0, "... ": "..." }
  }
}
```

*(numbers illustrative)*

How to read it:

- **`decision_ms`** is the end‑to‑end per‑image cost. Prefer **`p50` / `p90`**
  over `mean` / `max`: the first call to each voter includes a one‑time model
  load (cold start) that inflates the tail.
- **`per_voter_ms`** is each voter measured in isolation. The **`n` ("ran … ×")**
  is lower than the sample count for the open‑vocab voters because the ensemble
  **cascades** — the deferred SigLIP / MobileCLIP voters are skipped on clearly
  allowed images (see `IMGEDGE_SIGLIP_GATE` in the
  [configuration reference](configuration.md)), so they only run in the decision
  band. That's why the *average* image is cheap even when a voter is heavy.
- **Comparing model counts** — two ways:
  1. **Run each config** (base / +SigLIP / +MobileCLIP / both) and compare
     `decision_ms` `p50`/`p90`. Direct and unambiguous.
  2. **Derive from one 4‑model run** — the marginal cost of a voter is roughly
     its `per_voter_ms` on the images where it ran, so dropping it lowers
     `decision_ms` by about that much on those images. This lets a single (slow)
     run estimate the 3‑vs‑4‑model latency delta as well as the quality.

Latency reflects **your** hardware and execution provider (CPU vs GPU/NPU — see
[GPU / NPU acceleration](../README.md#optional-gpu--npu-acceleration)); use it for
*relative* comparisons between configurations on the same machine.

## Safety

The harness never renders or writes an image: it reads the encrypted zip in
memory, decodes only as far as classification needs, and emits only counts,
rates, and per‑file numeric scores. Keep it that way — if you extend it, don't
add any path that writes, previews, or logs pixels. See the handling‑the‑datasets
note in [CONTRIBUTING](../CONTRIBUTING.md).
