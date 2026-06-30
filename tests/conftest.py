"""Test bootstrap: pin token/cache via env so importing the server is side-effect
free. Modules are imported as ``imgedge.*`` (install with ``pip install -e .``).
"""

import os
import sys
from pathlib import Path

# Make the dev ``tools/`` scripts (e.g. eval_filter) importable from tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

os.environ.setdefault("IMGEDGE_TOKEN", "test-token")
os.environ.setdefault("IMGEDGE_CACHE_FILE", "none")
os.environ.setdefault("IMGEDGE_LOG_FILE", "none")
