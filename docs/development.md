# Developer guide

How to set up, build, test, and benchmark ImgEdge from source. For *using* the
extension see the [Quick start](../README.md#quick-start); for the HTTP/CLI
surface see the [interface reference](api.md); for every tunable see the
[configuration reference](configuration.md).

## Prerequisites

- **Python 3.13+** — the classifier backend.
- **Node.js** — the extension's ESLint and packaging tooling.
- **Git**.
- **PowerShell 7+** (Windows) — for [`package.ps1`](../package.ps1) and the
  optional AppContainer decode sandbox.
- *Optional:* a GPU/NPU for the ONNX backend (see
  [GPU / NPU acceleration](../README.md#optional-gpu--npu-acceleration)).

## Get started

```powershell
git clone https://github.com/mcb0035/imgedge.git
cd imgedge
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows; elsewhere: source .venv/bin/activate
pip install -e ".[dev]"             # classifier + lint / test / benchmark toolchain
imgedge-download-models             # fetch + verify the vision model + taxonomy (~21 MB)
```

Optional feature extras (add to the install as needed, e.g.
`pip install -e ".[dev,voters]"`):

| Extra | Adds |
| --- | --- |
| `voters` | `timm` + `torch` — the optional ImageNet voter |
| `siglip` | `transformers` + `sentencepiece` — the SigLIP voter |
| `mobileclip` | `open_clip_torch` — the MobileCLIP voter |
| `onnx` | `onnxruntime` — the GPU/NPU backend |
| `eval` | `pyzipper` — the encrypted-dataset evaluation tooling |

Run the classifier with `imgedge-server` (it prints an access token), then load
the repository folder as an unpacked extension per the
[Quick start](../README.md#quick-start).

## Build

**Python package** (setuptools backend):

```powershell
pip install -e .        # editable install for development
python -m build         # optional: wheel + sdist into dist/  (pip install build first)
```

**Extension** — there is no build step; load the repository folder unpacked
during development. Build a store-ready package with PowerShell:

```powershell
.\package.ps1           # -> dist\imgedge-<version>.zip  (Chrome Web Store / Edge Add-ons)
.\package.ps1 -Crx      # also dist\imgedge.crx (+ dist\imgedge.pem on first run)
```

See [Packaging for distribution](../README.md#packaging-for-distribution) for the
store-upload details.

## Test

**Python** ([pytest](https://docs.pytest.org/)):

```powershell
pytest                                                                            # full suite, quiet
pytest -m "not perf" --cov=imgedge --cov-report=term-missing --cov-fail-under=55  # the CI core gate (>= 55 %)
pytest -m perf                                                                    # performance-regression guards
pytest tests/test_voting.py -k evidence                                           # a single file / selection
```

The decode-sandbox / AppContainer tests are Windows-only and skip elsewhere (they
run in the **Windows (tests)** CI job).

**Extension JavaScript** ([ESLint](https://eslint.org/), flat config):

```powershell
npm ci
npx eslint .
```

**Pre-commit** — run the lint/format/compile checks on every commit:

```powershell
pip install pre-commit && pre-commit install
npm install        # provides the eslint hook
```

Everything above is enforced by CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml))
on every pull request.

## Benchmark

Two ready-to-run scripts measure the real decode path — full details in
[`benchmark/README.md`](../benchmark/README.md):

```powershell
python benchmark/bench_decode.py     # warm decode latency: in-process vs subprocess pool vs AppContainer
python benchmark/footprint.py        # resident RAM / private commit of the server + decode workers (Windows)
```

Noise-free, instruction-count microbenchmarks (decode / salience / voting) run
through [CodSpeed](https://codspeed.io/):

```powershell
pytest benchmark/ --codspeed
```

In CI these run as the **Performance guards** job (`pytest -m perf`) and the
**CodSpeed** workflow, which comments per-benchmark deltas on each PR.

## Continuous integration

Every push and pull request runs the checks below, and a pull request must be
green to merge. All third-party actions are pinned to a full commit SHA.

[`ci.yml`](../.github/workflows/ci.yml) is the core gate:

| Job | What it runs |
| --- | --- |
| **Python (lint + compile + tests)** | `ruff check`, `ruff format --check`, `py_compile`, and `pytest` with the ≥ 55 % coverage gate |
| **Extension JS (eslint)** | `npx eslint .` over the extension front-end |
| **Dependency audit (pip-audit)** | audits the pinned runtime (gating) and the optional voters (report-only) |
| **Dependency review (PR)** | fails a PR that introduces a new high-severity advisory |
| **Windows (tests)** | `pytest -m "not perf"` on `windows-latest` — covers the decode sandbox / AppContainer |
| **Performance guards** | `pytest -m perf` — relative decode / IPC regression checks |

Alongside it:

- **CodeQL** — static analysis for Python, JavaScript, and the Actions workflows.
- **[OpenSSF Scorecard](../.github/workflows/scorecard.yml)** — supply-chain
  posture, surfaced on the README badge.
- **[CodSpeed](../.github/workflows/codspeed.yml)** — instruction-count
  benchmarks that comment per-PR deltas.
- **ClusterFuzzLite** — a short fuzzing campaign over the image-decode path on
  each PR.
- **[`release.yml`](../.github/workflows/release.yml)** — builds and publishes
  the extension package for a tagged release.

Run the same checks locally before pushing (see [Test](#test) and
[Benchmark](#benchmark)); `pre-commit` wires the lint / format / compile subset
into every commit.

## See also

- [Interface reference](api.md) — the local HTTP API and CLI.
- [Configuration reference](configuration.md) — every popup setting and
  `IMGEDGE_*` variable.
- [Threat model](threat-model.md) · [Security policy](../SECURITY.md).
- [CONTRIBUTING](../CONTRIBUTING.md) — contribution process and the standards a
  change has to meet.
