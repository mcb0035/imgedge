# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Fuzz the untrusted image-decode path.

This is the classifier's real attack surface: it fetches image bytes supplied by
a web page and decodes them with Pillow. The harness drives `open_guarded`
(the decode-hardening entry point) with arbitrary bytes and forces a full codec
run, hunting for crashes, hangs, or uncaught errors that a hostile image could
trigger. Built/run in CI via ClusterFuzzLite (see .clusterfuzzlite/).
"""

import sys

import atheris

with atheris.instrument_imports():
    from PIL import Image

    from imgedge.inat.inat_filter import open_guarded

# Exceptions a hostile/garbage input is *expected* to raise (a rejected image,
# an unparseable/truncated file). Anything else escaping is a bug worth a report.
_EXPECTED = (
    ValueError,  # open_guarded size/format rejection
    OSError,  # PIL UnidentifiedImageError / truncated file (both subclass OSError)
    SyntaxError,
    EOFError,
    Image.DecompressionBombError,
    NotImplementedError,
)


def test_one_input(data):
    try:
        with open_guarded(data) as img:
            img.convert("RGB").resize((16, 16))  # force the codec to actually decode
    except _EXPECTED:
        pass


def main():
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
