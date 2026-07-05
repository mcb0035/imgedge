#!/usr/bin/env python3
# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Single source of truth for the project version: ``pyproject.toml``.

``src/imgedge/__init__.py`` (``__version__``), the browser-extension manifest,
and the npm ``package.json`` / ``package-lock.json`` each carry a *literal*
version string. This script propagates the canonical ``[project].version`` from
``pyproject.toml`` into all of them so they never drift.

Usage::

    python tools/sync_version.py            # rewrite manifest / package(-lock).json / __init__
    python tools/sync_version.py --check     # exit 1 if out of sync (CI / pre-commit)
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Each target: the regex whose group 2 is the version, and how many leading
# occurrences to rewrite. package-lock.json repeats the project version at the
# root *and* under packages[""]; those two precede every dependency version, so
# rewriting the first two leaves dependency versions untouched.
_JSON_FIELD = r'("version"\s*:\s*")([^"]+)(")'
TARGETS = {
    "extension/manifest.json": (_JSON_FIELD, 1),
    "package.json": (_JSON_FIELD, 1),
    "package-lock.json": (_JSON_FIELD, 2),
    "src/imgedge/__init__.py": (r'(__version__\s*=\s*")([^"]+)(")', 1),
}


def canonical_version() -> str:
    """The one true version, read from pyproject.toml."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version = "([^"]+)"', text)
    if not match:
        sys.exit("sync_version: no version found in pyproject.toml")
    return match.group(1)


def main() -> int:
    check = "--check" in sys.argv
    version = canonical_version()
    drifted = []
    for name, (pattern, count) in TARGETS.items():
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        # manifest.json's manifest_version is an int (never captured by the
        # "version": "..." pattern); package-lock.json rewrites its first two
        # occurrences (root + packages[""]) -- see TARGETS.
        updated = re.sub(pattern, rf"\g<1>{version}\g<3>", text, count=count)
        if updated != text:
            drifted.append(name)
            if not check:
                path.write_text(updated, encoding="utf-8")
    if check and drifted:
        print(
            f"sync_version: {', '.join(drifted)} out of sync with pyproject "
            f"({version}); run: python tools/sync_version.py",
            file=sys.stderr,
        )
        return 1
    if drifted:
        print(f"sync_version: set version {version} in {', '.join(drifted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
