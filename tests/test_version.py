"""The extension manifest and the Python package version must stay in lockstep."""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _pyproject_version():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'(?m)^version = "([^"]+)"', text)
    assert m, "no version found in pyproject.toml"
    return m.group(1)


def test_manifest_and_pyproject_versions_match():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))["version"]
    assert manifest == _pyproject_version(), f"manifest {manifest!r} != pyproject"
