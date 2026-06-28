"""Test bootstrap.

The classifier runs as loose, in-place scripts (no installable package), so mirror
the sys.path wiring the server does and pin token/cache via env, so importing
``server`` doesn't touch the real home directory.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("classifier", "inat", "voters"):
    sys.path.insert(0, str(ROOT / sub))

os.environ.setdefault("IMGEDGE_TOKEN", "test-token")
os.environ.setdefault("IMGEDGE_CACHE_FILE", "none")
