"""Test bootstrap: pin token/cache via env so importing the server is side-effect
free. Modules are imported as ``imgedge.*`` (install with ``pip install -e .``).
"""

import os

os.environ.setdefault("IMGEDGE_TOKEN", "test-token")
os.environ.setdefault("IMGEDGE_CACHE_FILE", "none")
