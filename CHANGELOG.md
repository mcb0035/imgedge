# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Internationalized the extension (i18n).** All user-facing strings — the
  popup UI, the in-page "Blocked" placeholder, the right-click menu items, and
  the toolbar tooltip — now come from `extension/_locales/en/messages.json` via
  the standard WebExtension i18n API (`chrome.i18n.getMessage`, `__MSG_…__` in
  the manifest, and a small `data-i18n` loader in the popup). Adding a language
  is now just dropping in `_locales/<lang>/messages.json` — no code changes. A
  new `tests/js/i18n.test.mjs` asserts every referenced key is defined and every
  defined message is used, so the catalogue can't drift. See
  [docs/development.md](docs/development.md#internationalization-i18n).
- **Signed releases + optional store publishing.** The release workflow now
  writes a `SHA256SUMS` and signs it with a **keyless Sigstore signature**
  (`cosign sign-blob`, OIDC — no stored key), then **self-verifies it**
  (`cosign verify-blob`) so a bad signature fails the release before anything is
  attested or published — alongside the existing SLSA build-provenance
  attestation, attaching both to the GitHub Release;
  [SECURITY.md](SECURITY.md#verifying-a-release) documents the `cosign
  verify-blob` / `gh attestation verify` / checksum steps. Dormant, opt-in jobs
  publish to the **Chrome Web Store** and **Edge Add-ons** (gated on the
  `PUBLISH_CHROME` / `PUBLISH_EDGE` repo variables + their secrets), and a
  **self-hosted signed `.crx`** is built when `CRX_PRIVATE_KEY` is set. See
  [docs/development.md](docs/development.md#versioning--releases).
- **Settings export / import.** The popup's new **Advanced → Backup** section
  saves your setup to a JSON file and loads it back. The file contains only the
  detection mode, tuning sliders, toggles, and endpoint — never the access token
  or the allow/block lists — so it holds no secrets or browsing URLs. Import
  applies only those validated fields, keeps the existing token, and rejects any
  non-local endpoint. The popup also now states that settings live in
  `chrome.storage.local` and never leave the machine (see `PRIVACY.md`).
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

- **Pinned the ClusterFuzzLite fuzzing base image by digest.** The
  `.clusterfuzzlite/Dockerfile` now references
  `gcr.io/oss-fuzz-base/base-builder-python` by `@sha256:…` instead of the
  floating tag, so fuzz builds are reproducible and a swapped base image can't
  slip in (OpenSSF Scorecard *Pinned-Dependencies*: containerImage 0/1 → 1/1).
  Bump the digest periodically to pick up base-image updates.
- **Accessibility: popup contrast fixes + keyboard-dismissable debug overlay +
  a11y doc.** The popup's muted and status text now uses CSS custom properties
  tuned for **>= 4.5:1 contrast (WCAG 1.4.3)** in *both* light and dark modes (via
  a `prefers-color-scheme` override); the previous fixed greys/ambers (`#888`,
  `#b8860b`) fell to ~3.3-3.5:1 and were hard to read in one mode. The "explain
  decision" debug overlay is now focusable and dismissable with **Esc** (it was
  mouse-click only). New [`docs/accessibility.md`](docs/accessibility.md) records
  the accessibility posture (keyboard operability, labelled controls,
  colour-plus-text status, the blocked-image placeholder's `role` / focus / text
  alternative) and its honest scope.
- **`sync_version.py` now also keeps `package-lock.json` in step** with the
  canonical `pyproject.toml` version (its root and `packages[""]` fields, leaving
  every dependency version untouched); the pre-commit hook and
  `tests/test_version.py` now cover it too. This fixes the lockfile version, which
  had drifted to `0.1.0` while the project was `0.3.0`.
- **Added an architecture overview + refreshed stale docs.** New
  [`docs/architecture.md`](docs/architecture.md) documents the high-level design
  (components, the request→verdict lifecycle, and trust boundaries); the README
  "How it works" section + diagram now include the SigLIP / MobileCLIP voters and
  the Detection-mode presets (they previously described only iNat + timm). The
  OpenSSF Best Practices badge is linked on the README front page.
- **Documented the cryptography & network-protocol posture** in `SECURITY.md` for
  the OpenSSF Best Practices "silver" criteria: credential/key storage separation
  (token in its own `600` file, never in logs/cache/config; the `.crx` key only a
  transient CI secret), a protocol map (HTTPS-only downloads, optional-TLS public
  image fetch, loopback-only API), TLS 1.2/1.3 with certificate + hostname
  verification on by default (kept even under the SSRF IP-pinning), no private
  headers sent over external TLS, and crypto-algorithm agility. Documentation
  only — no behaviour change.
- **Documented response & fix SLAs and a release-notes vulnerability policy.**
  `SECURITY.md` now states initial-response targets (≤ 14 days to acknowledge a
  vulnerability report or a bug report; ≤ 30 days an enhancement request), a
  ≤ 60-day fix target for medium-or-higher severity issues (including those found
  by static/dynamic analysis), and that release notes list every publicly known
  vulnerability in ImgEdge's own code that had a CVE at release time.
  `CONTRIBUTING.md` makes these binding on contributors and records that the test
  and fuzzing configs run with assertions enabled. Targets are scoped for a
  single maintainer. (Also refreshed the stale supported version `0.2.0` -> `0.3.0`.)
- **Pinned `training/requirements.txt` to exact versions** (`torch==2.12.1`,
  `torchvision==0.27.1`, `onnx==1.22.0`, `onnxruntime==1.27.0`, `pillow==12.2.0`,
  `numpy==2.5.0`) in place of `>=` floors. This clears the OSV/Scorecard warnings
  that flagged the old floor versions (`pillow` 10.0, `torch` 2.2) which a `>=`
  range resolves to during scanning — **no real exposure**: the shipped core and
  the pinned optional voters were already current and clean (confirmed by
  `pip-audit -s osv`), and `training/` is a dev-only fine-tune pipeline that is
  never installed by end users. Every `requirements.txt` in the repo is now pinned.
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

### Security

- **Hardened `/classify` request-input validation (CWE-20).** The server now
  type/shape-checks every field of the request body at the boundary: the body
  must be a JSON object, and `url`/`data` must be strings and `meta` an object
  (each otherwise treated as absent) — alongside the existing `[0,1]` clamping of
  `threshold`/`salience` and the allowlisted `profile`. Previously a local client
  sending a wrong-typed value (e.g. a numeric `data`, or a top-level JSON array)
  could trigger an unhandled exception (HTTP 500) instead of a clean verdict;
  such requests are now normalized/rejected gracefully. `_url_allowed` and
  `fetch_image_bytes` also reject non-string URLs up front. Not remotely
  exploitable (the endpoint is loopback-only and token-gated), but it closes an
  input-validation gap in line with the threat model. Regression tests added to
  `tests/test_server_http.py`.

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
