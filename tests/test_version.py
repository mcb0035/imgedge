# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""The extension manifest and the Python package version must stay in lockstep."""

import json
import pathlib
import re

import imgedge

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _pyproject_version():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'(?m)^version = "([^"]+)"', text)
    assert m, "no version found in pyproject.toml"
    return m.group(1)


def test_manifest_and_pyproject_versions_match():
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))["version"]
    assert manifest == _pyproject_version(), f"manifest {manifest!r} != pyproject"


def test_package_json_and_pyproject_versions_match():
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    assert pkg == _pyproject_version(), f"package.json {pkg!r} != pyproject"


def test_package_lock_and_pyproject_versions_match():
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    want = _pyproject_version()
    assert lock["version"] == want, f"package-lock root {lock['version']!r} != pyproject"
    assert lock["packages"][""]["version"] == want, "package-lock packages[''] out of sync"


def test_runtime_version_matches_pyproject():
    assert imgedge.__version__ == _pyproject_version(), f"imgedge.__version__ {imgedge.__version__!r} != pyproject"
