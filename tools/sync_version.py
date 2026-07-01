#!/usr/bin/env python3
"""Single source of truth for the project version: ``pyproject.toml``.

``src/imgedge/__init__.py`` (``__version__``), the browser extension manifest,
and the npm package each carry a *literal* version string. This script
propagates the canonical ``[project].version`` from ``pyproject.toml`` into all
three so they never drift.

Usage::

    python tools/sync_version.py            # rewrite manifest.json / package.json
    python tools/sync_version.py --check     # exit 1 if out of sync (CI / pre-commit)
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Files that carry a literal version, and the pattern whose group 2 is the value.
_JSON_FIELD = r'("version"\s*:\s*")([^"]+)(")'
TARGETS = {
    "manifest.json": _JSON_FIELD,
    "package.json": _JSON_FIELD,
    "src/imgedge/__init__.py": r'(__version__\s*=\s*")([^"]+)(")',
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
    for name, pattern in TARGETS.items():
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        # Only the first match (manifest.json's manifest_version is an int, so it
        # is never captured by the "version": "..." pattern).
        updated = re.sub(pattern, rf"\g<1>{version}\g<3>", text, count=1)
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
