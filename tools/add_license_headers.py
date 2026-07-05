#!/usr/bin/env python3
# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Insert (or verify) the standard copyright + SPDX license header in every
tracked source file.

Header, per the OpenSSF `copyright_per_file` / `license_per_file` criteria:

    Copyright the ImgEdge contributors.
    SPDX-License-Identifier: Apache-2.0

rendered in the comment syntax of each file type. JSON files are skipped (JSON
has no comment syntax); docs and generated lock files are out of scope.

Usage (from the repo root):
    python tools/add_license_headers.py          # insert where missing (idempotent)
    python tools/add_license_headers.py --check   # exit 1 if any file lacks it
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

COPYRIGHT = "Copyright the ImgEdge contributors."
SPDX = "SPDX-License-Identifier: Apache-2.0"
MARKER = "SPDX-License-Identifier"

# git pathspecs for the files we header (tracked files only; no venv/build dirs).
PATTERNS = [
    "*.py",
    "*.js",
    "*.mjs",
    "*.css",
    "*.html",
    "*.sh",
    "*.ps1",
    "*.yml",
    "*.yaml",
    "*Dockerfile",
    "pyproject.toml",
]

# extension / filename -> comment style
HASH, SLASH, CSS, HTML = "hash", "slash", "css", "html"
SUFFIX_STYLE = {
    ".py": HASH,
    ".sh": HASH,
    ".ps1": HASH,
    ".yml": HASH,
    ".yaml": HASH,
    ".toml": HASH,
    ".js": SLASH,
    ".mjs": SLASH,
    ".css": CSS,
    ".html": HTML,
}


def _style(path: Path) -> str:
    if path.name == "Dockerfile" or path.name.endswith("Dockerfile"):
        return HASH
    return SUFFIX_STYLE[path.suffix]


def _header(style: str) -> list[str]:
    if style == HASH:
        return [f"# {COPYRIGHT}", f"# {SPDX}"]
    if style == SLASH:
        return [f"// {COPYRIGHT}", f"// {SPDX}"]
    if style == CSS:
        return [f"/* {COPYRIGHT} */", f"/* {SPDX} */"]
    if style == HTML:
        return [f"<!-- {COPYRIGHT} -->", f"<!-- {SPDX} -->"]
    raise ValueError(style)


def _insert_index(lines: list[str], style: str) -> int:
    """Where to put the header: after a shebang and/or encoding cookie (hash
    files) or after a leading <!doctype> (html); otherwise the top."""
    idx = 0
    if lines and lines[0].startswith("#!"):
        idx = 1
    if style == HASH and idx < 2 and idx < len(lines) and re.search(r"coding[:=]", lines[idx]):
        idx += 1
    if style == HTML:
        for i, ln in enumerate(lines[:3]):
            if ln.strip().lower().startswith("<!doctype"):
                idx = i + 1
                break
    return idx


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", *PATTERNS],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return [Path(p) for p in out if p.strip()]


def main() -> int:
    check = "--check" in sys.argv[1:]
    missing: list[Path] = []
    changed: list[Path] = []
    for path in _tracked_files():
        text = path.read_text(encoding="utf-8")
        if MARKER in text:
            continue
        if check:
            missing.append(path)
            continue
        style = _style(path)
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.split(newline)
        at = _insert_index(lines, style)
        lines[at:at] = _header(style)
        # newline="" keeps the newlines we chose (no OS translation), so a file's
        # existing LF/CRLF style is preserved rather than flipped on Windows.
        path.write_text(newline.join(lines), encoding="utf-8", newline="")
        changed.append(path)

    if check:
        if missing:
            print("Missing license header in:")
            for p in missing:
                print(f"  {p.as_posix()}")
            return 1
        print("All source files carry the SPDX license header.")
        return 0

    for p in changed:
        print(f"headed {p.as_posix()}")
    print(f"\n{len(changed)} file(s) updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
