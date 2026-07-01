# Developer guide

How to set up, build, test, and benchmark ImgEdge from source. For *using* the
extension see the [Quick start](../README.md#quick-start); for the HTTP/CLI
surface see the [interface reference](api.md); for every tunable see the
[configuration reference](configuration.md).

> **Shells & platforms.** Commands are shown for **PowerShell 7** (`pwsh` —
> MIT-licensed, cross-platform). On bash/zsh, activate the venv with
> `source .venv/bin/activate`, set variables with `export VAR=value`, and use
> `curl` / `cat` where the examples use `Invoke-RestMethod` / `Get-Content`. The
> classifier and its tests are cross-platform (CI runs on Linux **and** Windows);
> only the AppContainer decode sandbox and
> [`footprint.py`](../benchmark/footprint.py) are Windows-specific. The **entire
> build/test toolchain is FLOSS** — pip, setuptools, pytest, Ruff, ESLint,
> pre-commit, and PowerShell 7.

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

**Extension JavaScript** ([ESLint](https://eslint.org/), flat config, plus
[`node:test`](https://nodejs.org/api/test.html) unit tests):

```powershell
npm ci
npx eslint . --max-warnings 0
npm test           # node:test unit tests for background.js / popup.js
```

The JS tests live in [`tests/js/`](../tests/js/) and evaluate the real classic
scripts in a `node:vm` sandbox (with `chrome` / DOM / `crypto` mocked), so add a
test there alongside any change to the extension's logic.

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
green to merge. Lint findings are treated as errors — Ruff's `W` (warning) rules
fail `ruff check`, and ESLint runs with `--max-warnings 0` — so warnings are
addressed before merge, never accumulated. All third-party actions are pinned to
a full commit SHA.

[`ci.yml`](../.github/workflows/ci.yml) is the core gate:

| Job | What it runs |
| --- | --- |
| **Python (lint + compile + tests)** | `ruff check`, `ruff format --check`, `py_compile`, and `pytest` with the ≥ 55 % coverage gate |
| **Extension JS (lint + tests)** | `npx eslint .` and `node --test` over the extension front-end |
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

## Versioning & releases

### How the version is defined

The version lives in **one** place — `[project].version` in
[`pyproject.toml`](../pyproject.toml). [`tools/sync_version.py`](../tools/sync_version.py)
propagates that canonical value into the three files that each need a *literal*
copy:

| File | Field |
| --- | --- |
| [`manifest.json`](../manifest.json) | `"version"` — the published extension version |
| [`package.json`](../package.json) | `"version"` |
| [`src/imgedge/__init__.py`](../src/imgedge/__init__.py) | `__version__` — runtime / `/health` |

A [pre-commit](../.pre-commit-config.yaml) hook re-syncs whenever one of those
files changes, and [`tests/test_version.py`](../tests/test_version.py) fails CI if
they ever drift — so they can't fall out of step. Bump the version following
[SemVer](https://semver.org/) (patch / minor / major by the kind of change):

```powershell
# edit [project].version in pyproject.toml, then propagate it:
python tools/sync_version.py           # writes manifest.json / package.json / __init__.py
python tools/sync_version.py --check    # verify only (what CI + pre-commit run)
```

### Cutting a release from a PR

Releases are **tag-driven**: pushing a `vX.Y.Z` tag runs
[`release.yml`](../.github/workflows/release.yml), which builds the store ZIP and
publishes a GitHub Release. The tag must match the version already on `main`, so
bump first, merge, then tag.

1. **In the release PR** — bump `pyproject.toml`, run
   `python tools/sync_version.py`, and move the `## [Unreleased]` entries in
   [`CHANGELOG.md`](../CHANGELOG.md) under a new `## [X.Y.Z] - YYYY-MM-DD`
   heading (updating the link refs at the bottom). Merge the PR.
2. **Tag `main`** once the bump is merged:

   ```powershell
   git checkout main; git pull
   git tag -s vX.Y.Z -m "ImgEdge X.Y.Z"   # signed; must equal the pyproject/manifest version
   git push origin vX.Y.Z
   ```

3. **`release.yml` takes over** (on `windows-latest`): it verifies the tag matches
   `manifest.json`, builds the extension with [`package.ps1`](../package.ps1),
   attaches a signed build-provenance attestation, and creates the GitHub Release
   with auto-generated notes and the `dist/imgedge-<version>.zip` asset.

If the tag and `manifest.json` disagree the release job fails fast — a guard
against tagging before the version bump has merged.

## See also

- [Interface reference](api.md) — the local HTTP API and CLI.
- [Configuration reference](configuration.md) — every popup setting and
  `IMGEDGE_*` variable.
- [Threat model](threat-model.md) · [Security policy](../SECURITY.md).
- [CONTRIBUTING](../CONTRIBUTING.md) — contribution process and the standards a
  change has to meet.
