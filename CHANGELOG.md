# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Easy-mode detection presets.** The popup gains a **Fast / Balanced /
  Accurate** selector (iNat+timm / +MobileCLIP / +SigLIP) that picks the voter
  subset per request; the existing endpoint/token/threshold/salience controls
  move under an **Advanced** disclosure. Backed by a new per-request `profile`
  field on `POST /classify` and a `profiles` availability map on `/health` (so a
  preset whose voter isn't loaded is greyed out). `VoteEnsemble.classify` gains
  an `only=` voter-subset filter. See `docs/configuration.md`.
- **Inference-latency benchmark (`benchmark/bench_infer.py`).** Times each
  voter's forward pass and the 2-/3-/4-model profile totals (Fast / Balanced /
  Accurate / Maximum) on a seeded synthetic image — no real image or dataset
  needed. Thread-aware (`--threads`, prints the effective OMP/OpenBLAS/torch
  config) with a cross-platform "simulating weak hardware" recipe (optional
  container CPU/RAM caps via FLOSS Podman or Docker, Linux `taskset`/cgroups,
  Windows affinity/`powercfg`). See `benchmark/README.md`.
- **Eval harness: ensemble decision-latency profiling.** Each voter is timed and
  the report gains a `latency` block (per-image decision percentiles + per-voter
  cost), a progress meter (count / rate / ETA on stderr, `--no-progress` to
  silence), and `--siglip` / `--mobileclip` flags to pick the voter set per run
  (deterministic — no environment to set/unset). See `docs/evaluation.md`.

### Changed

- **Moved the browser-extension front-end into `extension/`** (`manifest.json`,
  `background.js`, `content.js`, `content.css`, `popup.*`, `icons/`), decluttering
  the repo root. Load-unpacked now targets `extension/`; packaging, the release
  workflow, the version-sync pre-commit hook, and the JS test harness were updated
  to match. Eval `--report <bare-name>` now writes under `reports/` (gitignored)
  rather than the repo root.
- **SigLIP and MobileCLIP voters now load when their extra is installed**
  (`IMGEDGE_SIGLIP` / `IMGEDGE_MOBILECLIP` default `0` -> `1`), matching how the
  timm voter already loads; set either to `0` to skip loading it (e.g. to save
  RAM). This makes the Balanced/Accurate presets selectable out of the box once
  the extras are installed. The eval harness is unaffected -- it pins both env
  vars per run.
- **Split the open-vocabulary block prompts by false-positive risk.** The SigLIP
  voter now defaults to the tight core arachnid prompts; the looser atypical
  prompts (egg sacs, molts, spiderlings, mites, specimen shots) are carried by
  the MobileCLIP voter only. SigLIP (weight 2.0) is the dominant web
  false-positive contributor while MobileCLIP is near-silent on web negatives, so
  this trims SigLIP's web false positives. Measured on the reference sets:
  SigLIP-only web FPR fell 1.05% -> 0.94% (target met) at 98.7% web-recall; the
  4-model holds ~91% recall at ~1.0% web FPR. `IMGEDGE_SIGLIP_PROMPTS` /
  `IMGEDGE_MOBILECLIP_PROMPTS` still override.

## [0.3.0] - 2026-06-30

### Changed

- **Recall-first filtering defaults**, calibrated against 1,530 arachnid images
  (iNaturalist) and 10,000 real web images (Open Images): block threshold
  `0.5 -> 0.18`, salience is now **boost-only** (amplifies large/photographic
  images, never suppresses small/stylised ones), and the timm look-alike
  contrast is **off by default** (`IMGEDGE_TIMM_CONTRAST_WEIGHT` `1.0 -> 0.0`)
  -- on real web imagery it suppressed recall for almost no false-positive
  benefit. Together: ~0% -> ~77% recall at ~1% false positives. The bare
  `spider` block term (which also matched *spider monkey*) is replaced with the
  explicit arachnid classes plus `spider web`.
- **README slimmed for docs:** the full `IMGEDGE_*` configuration table moved
  into `docs/configuration.md` (linked from a shorter Configuration section),
  with a new Documentation index and Contributing section.

### Added

- **Contributor + interface docs:** a `CONTRIBUTING.md` (how to obtain, give
  feedback, and the coding standards CI enforces), an interface reference
  (`docs/api.md` — the `/classify` + `/health` HTTP API and the CLI), and a
  configuration reference (`docs/configuration.md`), for the OpenSSF Best
  Practices badge.
- **MobileCLIP voter** (`src/imgedge/voters/mobileclip_voter.py`, off by
  default): a smaller/faster open-vocabulary alternative to the SigLIP voter
  (open_clip, default `MobileCLIP2-S0`) for when CPU latency matters more than
  the last point of recall. Enable with `IMGEDGE_MOBILECLIP=1` after
  `pip install -e ".[voters,mobileclip]"`. Calibrated on real data (offset
  `0.23`): ~87% recall at ~1% real-web false positives -- vs SigLIP's ~89% but
  far cheaper on CPU. Shares the arachnid block prompts
  with SigLIP, now expanded with atypical presentations (egg sacs, molts,
  spiderlings, mites, specimen shots) to widen coverage of the hard final ~10%.
- **Open-vocabulary SigLIP 2 voter** (`src/imgedge/voters/siglip_voter.py`,
  off by default): an optional third voter that scores images against free-text
  prompts using `google/siglip2-base-patch16-224` (Apache-2.0), catching
  arachnids the closed-vocabulary iNat/timm voters have no class for. Enable
  with `IMGEDGE_SIGLIP=1` after `pip install -e ".[voters,siglip]"`. Calibrated
  on real data (default `IMGEDGE_SIGLIP_WEIGHT` `2.0`): lifts recall ~79% -> ~89%
  at ~0.9% real-web false positives, since SigLIP is near-silent on non-arachnid
  imagery; re-tune `IMGEDGE_SIGLIP_WEIGHT` / `IMGEDGE_SIGLIP_GAIN` if you change
  the model or prompts. A **cascade gate** (`IMGEDGE_SIGLIP_GATE`, default
  `0.0`) skips the heavy model when the cheap voters already block; raise it to
  trade a little recall for fewer SigLIP runs.
- **iNat-confidence override:** when the iNaturalist model (trained on real
  living organisms) is at/above `IMGEDGE_INAT_OVERRIDE` confidence (default
  `0.9`), it blocks outright and the look-alike contrast voter can no longer
  veto it. Set `>1` to disable. Surfaced in `/health` and the debug breakdown.
- **Filtering evaluation harness** (`tools/eval_filter.py`): measures recall /
  false-positive rate, a threshold sweep, and a salience-strategy comparison
  over an AES-encrypted dataset, without ever displaying an image. Dev-only
  (`pip install -e ".[eval]"`).
- **CI security & coverage:** OpenSSF Scorecard analysis (weekly and on push,
  results published for the badge), a `dependency-review` check on pull
  requests (fails on high-severity advisories), StepSecurity Harden-Runner
  egress auditing on every Linux job, a Windows test job, and test-coverage
  reporting over the deterministic core modules (optional / Windows-only /
  model-dependent code is excluded) with a `--cov-fail-under` floor.
- **Developer guide** (`docs/development.md`): prerequisites, setup, build,
  test, benchmark, and a CI-pipeline overview, linked from the README and
  CONTRIBUTING.
- **Decode-path fuzzing:** a ClusterFuzzLite job runs a short Atheris campaign
  over the image decoder on each PR; the decode hardening was decoupled from the
  TFLite runtime so the fuzz target imports only numpy + Pillow.
- **Front-end and API tests:** `node:test` unit tests for the extension scripts
  (endpoint allow-list, sender-id guard, HMAC proof) in a `vm` sandbox, plus
  HTTP-layer tests for the classifier's `/classify` + `/health`.
- **OpenSSF Best Practices** groundwork: a Saltzer-Schroeder secure-design and
  OWASP/CWE common-errors mapping in the threat model, and a cryptography
  section in `SECURITY.md`.

### Fixed

- **Large images no longer fail open.** A photo above the 24 MP decode-bomb
  guard was previously rejected and shown unclassified; large JPEGs are now
  downscaled during decode (libjpeg DCT scaling, which never expands the full
  pixels into memory) and classified, with an absolute reject ceiling kept for
  true decompression bombs.
- **Documented install commands corrected:** the invalid `pip install ...
  onnxruntime*` wildcard in `SECURITY.md`, and the GPU/NPU conversion path now
  installs TensorFlow (required by `tf2onnx`) and a single ONNX Runtime build.
- **Version drift:** `imgedge.__version__` and `package.json` were stuck at
  `0.1.0` while the package was `0.2.0`.

### Changed

- **Supply-chain hardening:** pin all dependencies, dev tools, and GitHub
  Actions to exact versions / immutable commit SHAs (no floating ranges or
  mutable tags), and raise the Python floor to 3.13. Bumped to the latest
  stable releases (numpy 2.5, pillow 12.2, onnxruntime 1.27, ruff 0.15,
  pytest 9, pip-audit 2.10, pre-commit 4.6; CI Node 24).
- **Warnings are errors:** pytest `filterwarnings=error` and ESLint
  `--max-warnings 0`, so deprecations, resource leaks, and lint warnings fail CI.
- **Single source of version truth:** `pyproject.toml` is canonical;
  `tools/sync_version.py` propagates it to `manifest.json`, `package.json`, and
  `imgedge.__version__`, with a pre-commit + CI check keeping them in lockstep.

## [0.2.0] - 2026-06-29

### Added

- Apache-2.0 license, `NOTICE`, and third-party model attributions with an
  "adding a model" license checklist (`THIRD-PARTY-NOTICES.md`).
- STRIDE + LINDDUN threat model (`docs/threat-model.md`).
- Privacy disclosure (`PRIVACY.md`).
- Configurable classifier port via `IMGEDGE_PORT`.
- Optional out-of-process / Windows AppContainer decode sandbox.
- Release automation (tag `v*` → packaged GitHub Release) and a CI check that
  keeps the manifest and Python versions in lockstep.

### Security

- SSRF-hardened image fetch: connection pinned to the validated IP (closes the
  DNS-rebinding TOCTOU), NAT64/CGNAT/IPv4-mapped unwrapping, destination-port
  allow-list, optional host allow-list and HTTPS-only, content-type gate, and a
  per-host concurrency cap.
- Server-identity proof (HMAC challenge) so the extension detects a local
  port-squatter before sending the token; lean unauthenticated `/health`;
  per-connection read timeout (slowloris guard); HMAC-keyed verdict cache;
  atomic, owner-only token file; generic client error messages.
- Extension: verifies the server's identity before sending the token, restricts
  the endpoint to localhost, checks message `sender.id`, and masks the token
  field.

### Changed

- Friendlier startup: an already-running classifier is detected and reused
  (clean exit) instead of failing like a crash.

## [0.1.0]

### Added

- Initial ImgEdge: a Manifest V3 extension plus a local iNaturalist/timm voting
  classifier that hides a chosen image category (default: arachnids), entirely
  on-device. (Pre-versioned development; no dated release.)

[Unreleased]: https://github.com/mcb0035/imgedge/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/mcb0035/imgedge/releases/tag/v0.3.0
[0.2.0]: https://github.com/mcb0035/imgedge/releases/tag/v0.2.0
[0.1.0]: https://github.com/mcb0035/imgedge/releases/tag/v0.1.0
