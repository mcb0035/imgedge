# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Static file server for the Phase 0 spike with correct web MIME types.

Python's stdlib `http.server` (notably on Windows) serves `.mjs` as
`text/plain`, which browsers refuse to import as an ES module — and ONNX Runtime
Web loads its WASM glue via a dynamic `import()` of a `.mjs`. This wrapper fixes
the `.mjs` / `.js` / `.wasm` types and serves the current directory on loopback.

Run from inside spike/inbrowser-fast:  python serve.py [port]   (default 8080)
"""

import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, test

SimpleHTTPRequestHandler.extensions_map.update(
    {
        ".mjs": "text/javascript",
        ".js": "text/javascript",
        ".wasm": "application/wasm",
    }
)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    here = os.path.dirname(os.path.abspath(__file__))
    test(HandlerClass=partial(SimpleHTTPRequestHandler, directory=here), port=port, bind="127.0.0.1")
