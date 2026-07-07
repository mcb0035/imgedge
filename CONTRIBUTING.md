# Contributing to ImgEdge

[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/13448/badge)](https://www.bestpractices.dev/projects/13448)

Thanks for your interest! ImgEdge is a small, local-first privacy tool — a
Manifest V3 browser extension plus an on-device Python image classifier. This
page covers how to **get the code**, how to **give feedback**, and the
**standards a change has to meet** to be merged.

Please note that this project is released with a [Code of Conduct](CODE_OF_CONDUCT.md). By
participating in this project, you agree to abide by its terms.

## Get the software

```powershell
git clone https://github.com/mcb0035/imgedge.git
cd imgedge
pip install -e ".[dev]"      # classifier + lint/test toolchain
imgedge-download-models      # fetch + verify the vision model (~21 MB)
```

For the extension itself and end-user setup, see the
[README](README.md#quick-start). For the full setup, build, test, and benchmark
steps, see the [developer guide](docs/development.md). For the HTTP/CLI
interface, see the [API reference](docs/api.md); for every tunable, the
[configuration reference](docs/configuration.md).

## Give feedback

- **Bugs and feature ideas** — open a
  [GitHub issue](https://github.com/mcb0035/imgedge/issues). Please say what you
  expected, what happened, and (for bugs) the OS, Python version, browser, and
  steps to reproduce.
- **Questions / ideas** — start a
  [discussion](https://github.com/mcb0035/imgedge/discussions) or an issue.
- **Security vulnerabilities** — **do not** open a public issue. Use GitHub
  [private vulnerability reporting](https://github.com/mcb0035/imgedge/security/advisories/new)
  as described in [SECURITY.md](SECURITY.md).

This is a single-maintainer project, so responses are best-effort — but there are
concrete commitments: the maintainer **acknowledges bug reports within 14 days**
and **responds to enhancement requests within 30 days** (the answer may be "no"
or a discussion of merits). Security reports have their own response and fix
targets — see
[SECURITY.md → Response and fix targets](SECURITY.md#response-and-fix-targets).
These targets bind anyone triaging or reviewing on the project's behalf.

## Make a change

1. **Fork** and create a topic branch (`feat/…`, `fix/…`, `docs/…`, `ci/…`).
2. Make the change with a matching **test** and a
   [CHANGELOG](CHANGELOG.md) entry under `## [Unreleased]`.
3. Run the checks below locally.
4. **Sign off** every commit (`git commit -s`) to certify the
   [DCO](#developer-certificate-of-origin-dco).
5. Open a pull request describing the *why*, not just the *what*. Keep PRs
   focused — one concern per PR merges fastest.

**Testing policy.** Any change that adds or alters behaviour must add or update
automated tests that cover it, and bug fixes should include a regression test —
the CI coverage gate enforces this. As new functionality lands, its tests land
with it, in the same PR.

New to the codebase? The [README](README.md#project-layout) project-layout table
and the [threat model](docs/threat-model.md) are the fastest way in.

## Good first issues

New and casual contributors are welcome, and a contribution **need not add
functionality** — improving the docs, adding a test, or translating the UI all
help.

Beginner-friendly issues are tagged
[`good first issue`](https://github.com/mcb0035/imgedge/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22),
and larger scoped ones
[`help wanted`](https://github.com/mcb0035/imgedge/issues?q=is%3Aopen+is%3Aissue+label%3A%22help+wanted%22);
GitHub also gathers them on the project's
[contribute page](https://github.com/mcb0035/imgedge/contribute). If none are
open right now, pick any of the standing tasks below and **open an issue saying
you're taking it** so effort isn't duplicated — then follow
[Make a change](#make-a-change).

### Starter tasks

- **Translate the extension UI into another language.** The interface strings
  live in [`extension/_locales/en/messages.json`](extension/_locales/en/messages.json)
  (Chrome's `i18n` format — each entry has a `message` and a `description`). Add
  `extension/_locales/<code>/messages.json` for a new
  [locale code](https://developer.chrome.com/docs/extensions/reference/api/i18n#locales)
  (e.g. `es`, `de`, `fr`, `ja`), copy the English file, and translate **only the
  `message` values** — leave the keys and any `$1` / `$NAME$` placeholders
  unchanged. Verify with `npm test` (the
  [`i18n`](tests/js/i18n.test.mjs) test asserts every locale carries the same
  keys as English), then load the unpacked extension, switch your browser's
  display language to the new locale, and eyeball the popup. No coding needed
  beyond editing JSON.
- **Improve the documentation.** Add a troubleshooting entry, clarify a setup
  step, add a popup screenshot, expand the
  [accessibility notes](docs/accessibility.md), or fix typos across
  [`README.md`](README.md) and [`docs/`](docs/). Keep links valid and wrap prose
  like the surrounding text.
- **Add a test case.** Pick an edge case that isn't covered yet — a pure helper
  in [`extension/inbrowser/`](extension/inbrowser/) (`node:test`) or a function
  in [`src/imgedge/`](src/imgedge/) (`pytest`) — and add a focused test beside
  the existing ones in [`tests/`](tests/). It's the fastest way to learn a
  corner of the code. Run `npm test` / `pytest` to confirm it passes.
- **Benchmark the classifier on your hardware.** Run the suite in
  [`benchmark/`](benchmark/) (see [`benchmark/README.md`](benchmark/README.md))
  and report per-image decode + inference latency along with your CPU/GPU, OS,
  and browser. Real numbers across devices help us size the in-browser "Fast"
  mode. Paste them into an issue — no code change required.
- **Evaluate one of the saved candidate voter models.** The roadmap's
  [re-shop the ImageNet voter slot](docs/roadmap.md) task keeps an offline
  harness, [`tools/eval_third_voter.py`](tools/eval_third_voter.py), that scores
  whether an extra ImageNet voter lifts arachnid recall. Pick a candidate
  (`convnext_nano`, `tf_efficientnetv2_b0`, `regnety_016`, `resnet26d`,
  `xcit_tiny_12_p16_224`, `edgenext_small` — all Apache-2.0 / MIT) and run:

  ```powershell
  python tools/eval_third_voter.py <dataset.eval.zip> --model <name> --sample-per-class 2000 --threads 4
  ```

  Report the recall / FPR it prints against the iNat + timm baseline. You'll
  need an evaluation dataset — an **AES-encrypted zip** (see **Handling the
  arachnid datasets** below); without one, build a small set from public image
  URLs via `python -m tools.eval_filter build-urls …`
  ([docs/evaluation.md](docs/evaluation.md)). **Share the JSON report, never
  images.**

### Bigger tasks (open an issue to coordinate first)

- **Train or fine-tune a model to better recognize the blocked category.**
  Improve arachnid recall at a low false-positive rate with a model that stays
  **small and WASM-viable** (int8 ONNX, roughly ≤ 25 MB, runs under ONNX Runtime
  Web) and **permissively licensed**. Starting points: the voters in
  [`src/imgedge/voters/`](src/imgedge/voters/), the export / quantize tools in
  [`tools/`](tools/), and [`training/`](training/). Validate with
  `tools/eval_third_voter.py` and `tools/tune_inbrowser.py`, and share JSON
  reports, not images.
- **Curate a public evaluation set.** Assemble a small, correctly-licensed set
  of arachnid vs non-arachnid **image URLs** (plus a builder that uses
  [`tools/eval_filter.py`](tools/eval_filter.py)) so contributors without the
  private dataset can run evals. Per the dataset rules, contribute a **URL list
  and builder — never the images themselves**.

## Developer Certificate of Origin (DCO)

ImgEdge uses the [Developer Certificate of Origin](https://developercertificate.org/)
(DCO) as its contribution agreement. The DCO is a lightweight, in-commit way to
certify that **you wrote the contribution, or otherwise have the right to submit
it** under the project's Apache-2.0 license. It is short — read the full text at
<https://developercertificate.org/>.

You certify it by **signing off** each commit:

```powershell
git commit -s -m "your message"
```

That appends a trailer with your real name and email:

```text
Signed-off-by: Your Name <you@example.com>
```

Set `git config user.name` / `user.email` first (identical on bash/zsh). Forgot
one? `git commit --amend -s` fixes the last commit, or `git rebase --signoff
main` a whole branch. By signing off you agree to the DCO for that contribution;
anonymous or pseudonymous sign-offs are not accepted.

A CI check ([`dco.yml`](.github/workflows/dco.yml)) enforces this: a pull request
whose commits are not all signed off fails until you amend or rebase
(`--signoff`) and force-push. Automated dependency PRs from trusted bots
(currently Dependabot) are allow-listed and exempt from the sign-off check.

## License headers

Every source file begins with a two-line header, in that file's comment syntax:

```text
Copyright the ImgEdge contributors.
SPDX-License-Identifier: Apache-2.0
```

New source files should carry it. `python tools/add_license_headers.py` adds the
header to any tracked source file missing it (idempotent), and
`python tools/add_license_headers.py --check` verifies coverage — CI runs this
check on every push and pull request, so a missing header fails the build. JSON
files are exempt (JSON has no comment syntax).

## Requirements for acceptable contributions

These are the standards the CI gate enforces on every pull request
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)); a change has to pass
them to merge. For the full CI pipeline — every workflow and job, and what each
checks — see the [developer guide](docs/development.md#continuous-integration).

### Python

- **Lint + format with [Ruff](https://docs.astral.sh/ruff/)** — line length
  **120**, target **py313**, rule sets `E, F, W, I, B, UP`:

  ```powershell
  ruff check .
  ruff format --check .
  ```

- **Tests pass with coverage** — the always-on core must stay at **≥ 80 %**:

  ```powershell
  pytest -m "not perf" --cov=imgedge --cov-report=term-missing --cov-fail-under=80
  ```

- **Everything compiles** — `python -m py_compile` runs over the `classifier`,
  `inat`, and `voters` packages.
- **No new runtime dependencies** without discussion. Pin exact versions
  (`==`) and keep the `requirements*.lock` files in sync; `pip-audit` gates the
  required runtime and `dependency-review` fails a PR on a high-severity advisory.

### Extension JavaScript

- **Lint with [ESLint](https://eslint.org/)** (flat config,
  [`eslint.config.mjs`](eslint.config.mjs)) — warnings fail the build:

  ```powershell
  npm ci
  npx eslint . --max-warnings 0
  ```

- **Test with [`node:test`](https://nodejs.org/api/test.html)** — unit tests for
  the extension scripts live in [`tests/js/`](tests/js/) and run the real code in
  a `node:vm` sandbox:

  ```powershell
  npm test
  ```

- No `innerHTML` / `eval` / dynamic-code sinks — the content script runs in
  every frame of every site, so use `textContent` and keep the blast radius
  small.

### Both

- **Install the pre-commit hooks** so the above run on every commit:

  ```powershell
  pip install pre-commit && pre-commit install
  npm install    # provides the eslint hook
  ```

- **Conventional-commit messages** (`type(scope): summary`, e.g.
  `fix(fuzz): …`), and **sign your commits** (`git commit -S`) so they show as
  *Verified*.
- **Pin any new GitHub Action to a full commit SHA** (with a `# vX.Y.Z`
  comment) — the project keeps a clean OpenSSF Scorecard.

### Security & vulnerabilities

These requirements hold for every contribution, and for anyone triaging or
reviewing on the project's behalf:

- **Report vulnerabilities privately** — never in a public issue or PR. Use
  [private vulnerability reporting](https://github.com/mcb0035/imgedge/security/advisories/new)
  ([SECURITY.md](SECURITY.md)). The maintainer's response and fix targets
  (≤ 14-day acknowledgement; ≤ 60-day fix for medium-or-higher severity) are in
  [SECURITY.md → Response and fix targets](SECURITY.md#response-and-fix-targets).
- **List fixed vulnerabilities in the release notes.** A change that fixes a
  publicly known vulnerability in ImgEdge's *own* code must record it in the
  [CHANGELOG](CHANGELOG.md) with its CVE (or comparable) identifier and
  what/where it was fixed, per the
  [disclosure policy](SECURITY.md#release-notes-and-disclosure). Dependency
  advisories are handled by `pip-audit` / Dependabot / Scorecard, not re-listed.
- **Fix confirmed medium+ findings on time.** Any medium-or-higher severity
  (CVSS ≥ 4.0) exploitable vulnerability confirmed by static analysis (CodeQL,
  the Ruff ruleset) or dynamic analysis (the tests or the ClusterFuzzLite
  fuzzers) must be fixed within the project's ≤ 60-day target.
- **Keep assertions on during analysis.** Dynamic analysis runs *with assertions
  enabled* so faults surface before release: `pytest` runs without `-O` (so
  `assert` is live) and turns warnings into errors (`filterwarnings = ["error"]`
  in [`pyproject.toml`](pyproject.toml)), and the ClusterFuzzLite fuzzers build
  under AddressSanitizer. Don't weaken these — they are pre-deployment checks; the
  classifier's normal run ships without them.

### Handling the arachnid datasets — please read

ImgEdge exists so a user never has to see a spider. The evaluation datasets are
therefore **AES-encrypted zips**, and the tooling reads them into memory and
emits only JSON score reports — **images are never written to disk or
rendered**. If you work on the model/eval path:

- **Never commit dataset images** (or any un-encrypted arachnid imagery), and
  never add code that displays a sample image. The `.gitignore` already excludes
  the score-report JSON (`inat*.json`, `oi*.json`, `eval-report*.json`).
- Share results as the **JSON reports**, not screenshots.

## License

By contributing, you agree that your contributions are licensed under the
project's [Apache License 2.0](LICENSE) (inbound = outbound).
