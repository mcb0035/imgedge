# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Model/taxonomy integrity verification (download_models.py + server.py)."""

import hashlib

import imgedge.classifier.server as server
import imgedge.inat.download_models as download_models


def test_default_checksums_pinned():
    for fn in ("INatVision_Small_2_fact256_8bit.tflite", "taxonomy.csv", "taxonomy.json"):
        digest = download_models.CHECKSUMS.get(fn)
        assert digest is not None and len(digest) == 64


def test_sha256_of(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"abc")
    assert download_models.sha256_of(p) == hashlib.sha256(b"abc").hexdigest()


def test_verify_pinned_rejects_tampered(tmp_path):
    # A file whose name matches a pinned asset but whose bytes differ is refused.
    p = tmp_path / "taxonomy.csv"
    p.write_bytes(b"not the real taxonomy")
    assert server._verify_pinned(p) is False


def test_verify_pinned_allows_unpinned(tmp_path):
    # A custom / locally generated model (filename has no pin) passes through.
    p = tmp_path / "my_custom_model.tflite"
    p.write_bytes(b"whatever")
    assert server._verify_pinned(p) is True
