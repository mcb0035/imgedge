# Project governance

This document describes how ImgEdge is governed: how decisions are made, the
roles in the project, and who currently holds them. It sets clear expectations
for contributors and satisfies the project's "documented governance" goal.

## Model

ImgEdge uses a **single-maintainer ("benevolent dictator")** model. It is a
small, local-first privacy tool with one maintainer who owns the project's
direction and has the final say on all changes. This is a deliberate fit for the
project's current size; it may evolve toward shared maintainership if the
contributor base grows, in which case this document will be updated.

Anyone may propose changes, report issues, and take part in discussions — see
[CONTRIBUTING.md](CONTRIBUTING.md). As a FLOSS project (Apache-2.0), anyone is
also free to fork.

## Roles and responsibilities

### Maintainer

- **Who:** Matthew Bedford ([@mcb0035](https://github.com/mcb0035)) — the sole
  current maintainer.
- **Responsibilities:**
  - Sets the project's scope and direction and makes the final decision on
    issues, pull requests, and releases.
  - Reviews and merges pull requests; a change merges only with maintainer
    approval and a green CI run (see
    [CONTRIBUTING.md](CONTRIBUTING.md#requirements-for-acceptable-contributions)).
  - Cuts and signs releases (see
    [docs/development.md](docs/development.md#versioning--releases)).
  - Triages and fixes security reports within the documented targets
    ([SECURITY.md](SECURITY.md#response-and-fix-targets)).
  - Upholds and enforces the [Code of Conduct](CODE_OF_CONDUCT.md).
  - Maintains this governance document.

### Contributors

- **Who:** anyone who opens an issue or discussion, or submits a pull request.
- **Responsibilities:** follow [CONTRIBUTING.md](CONTRIBUTING.md) and the
  [Code of Conduct](CODE_OF_CONDUCT.md), and certify authorship of each
  contribution via the
  [Developer Certificate of Origin](CONTRIBUTING.md#developer-certificate-of-origin-dco).

## How decisions are made

- **Everyday changes** (bug fixes, docs, in-scope features) are decided through
  pull-request review: the maintainer reviews, requests changes if needed, and
  merges once CI is green.
- **Larger or contentious changes** (scope, architecture, new dependencies,
  security-relevant behaviour) should start as a
  [GitHub issue or discussion](https://github.com/mcb0035/imgedge/issues) so the
  approach can be agreed before code is written. The maintainer makes the final
  call.
- **Disputes** are resolved by the maintainer, who will explain the reasoning on
  the issue or PR thread. Because ImgEdge is FLOSS, forking always remains
  available as a last resort.

## Changing this document

Changes to governance are made by the maintainer through a pull request to this
file, so the history stays public.

## Related

- [CONTRIBUTING.md](CONTRIBUTING.md) — how to contribute, and the DCO.
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — expected conduct.
- [SECURITY.md](SECURITY.md) — reporting and response/fix targets.
