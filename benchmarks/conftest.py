"""Bootstrap for the CodSpeed benchmark suite.

Pins token/cache env so importing the server / voter modules is side-effect
free, mirroring ``tests/conftest.py``. Modules are imported as ``imgedge.*``
(install with ``pip install -e .``).
"""

import os

os.environ.setdefault("IMGEDGE_TOKEN", "bench-token")
os.environ.setdefault("IMGEDGE_CACHE_FILE", "none")
os.environ.setdefault("IMGEDGE_LOG_FILE", "none")
