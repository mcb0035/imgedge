# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
