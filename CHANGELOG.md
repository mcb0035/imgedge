# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

### Added

- **Open-vocabulary SigLIP 2 voter** (`src/imgedge/voters/siglip_voter.py`,
  off by default): an optional third voter that scores images against free-text
  prompts using `google/siglip2-base-patch16-224` (Apache-2.0), catching
  arachnids the closed-vocabulary iNat/timm voters have no class for. Enable
  with `IMGEDGE_SIGLIP=1` after `pip install -e ".[voters,siglip]"`; tune
  `IMGEDGE_SIGLIP_WEIGHT` / `IMGEDGE_SIGLIP_GAIN` against the eval harness.
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

### Changed

- **Supply-chain hardening:** pin all dependencies, dev tools, and GitHub
  Actions to exact versions / immutable commit SHAs (no floating ranges or
  mutable tags), and raise the Python floor to 3.13. Bumped to the latest
  stable releases (numpy 2.5, pillow 12.2, onnxruntime 1.27, ruff 0.15,
  pytest 9, pip-audit 2.10, pre-commit 4.6; CI Node 24).

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

[Unreleased]: https://github.com/mcb0035/imgedge/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/mcb0035/imgedge/releases/tag/v0.2.0
[0.1.0]: https://github.com/mcb0035/imgedge/releases/tag/v0.1.0
