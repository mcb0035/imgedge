# Contributing to ImgEdge

[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/13448/badge)](https://www.bestpractices.dev/projects/13448)

Thanks for your interest! ImgEdge is a small, local-first privacy tool — a
Manifest V3 browser extension plus an on-device Python image classifier. This
page covers how to **get the code**, how to **give feedback**, and the
**standards a change has to meet** to be merged.

## Get the software

```powershell
git clone https://github.com/mcb0035/imgedge.git
cd imgedge
pip install -e ".[dev]"      # classifier + lint/test toolchain
imgedge-download-models      # fetch + verify the vision model (~21 MB)
```

For the extension itself and end-user setup, see the
[README](README.md#quick-start). For the HTTP/CLI interface, see the
[API reference](docs/api.md); for every tunable, the
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

This is a single-maintainer hobby project, so please allow reasonable time for a
response.

## Make a change

1. **Fork** and create a topic branch (`feat/…`, `fix/…`, `docs/…`, `ci/…`).
2. Make the change with a matching **test** and a
   [CHANGELOG](CHANGELOG.md) entry under `## [Unreleased]`.
3. Run the checks below locally.
4. Open a pull request describing the *why*, not just the *what*. Keep PRs
   focused — one concern per PR merges fastest.

**Testing policy.** Any change that adds or alters behaviour must add or update
automated tests that cover it, and bug fixes should include a regression test —
the CI coverage gate enforces this. As new functionality lands, its tests land
with it, in the same PR.

New to the codebase? The [README](README.md#project-layout) project-layout table
and the [threat model](docs/threat-model.md) are the fastest way in.

## Requirements for acceptable contributions

These are the standards the CI gate enforces on every pull request
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)); a change has to pass
them to merge.

### Python

- **Lint + format with [Ruff](https://docs.astral.sh/ruff/)** — line length
  **120**, target **py313**, rule sets `E, F, W, I, B, UP`:

  ```powershell
  ruff check .
  ruff format --check .
  ```

- **Tests pass with coverage** — the always-on core must stay at **≥ 55 %**:

  ```powershell
  pytest -m "not perf" --cov=imgedge --cov-report=term-missing --cov-fail-under=55
  ```

- **Everything compiles** — `python -m py_compile` runs over the `classifier`,
  `inat`, and `voters` packages.
- **No new runtime dependencies** without discussion. Pin exact versions
  (`==`) and keep the `requirements*.lock` files in sync; `pip-audit` gates the
  required runtime and `dependency-review` fails a PR on a high-severity advisory.

### Extension JavaScript

- **Lint with [ESLint](https://eslint.org/)** (flat config,
  [`eslint.config.mjs`](eslint.config.mjs)):

  ```powershell
  npm ci
  npx eslint .
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
