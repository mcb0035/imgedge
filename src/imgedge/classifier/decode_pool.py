"""Optional out-of-process image decode (prototype, feature/sandbox).

Runs the memory-unsafe part — the Pillow format decode in ``open_guarded`` — in a
recycled worker pool, and returns only a trusted uint8 RGB array to the parent.
A crash/exploit in a decoder is then contained to a child process (the pool
replaces it), and workers are recycled every N tasks to bound how long any
compromised worker lives.

IMPORTANT: this is a CRASH + RECYCLE boundary, not an OS sandbox. The children
are ordinary processes (no AppContainer / restricted token on Windows, no
seccomp / namespaces on Linux), so a decoder exploit could still do what the
user can. True OS confinement is the follow-up; this prototype exists to measure
the warm-path overhead and provide crash isolation. Enable with IMGEDGE_SANDBOX=1.
"""

from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

import numpy as np


def _decode(raw, cap):
    # Imported inside the worker so the parent process needn't import Pillow.
    from imgedge.inat.inat_filter import open_guarded

    with open_guarded(raw) as img:
        rgb = img.convert("RGB")
        ow, oh = rgb.size
        if cap and max(ow, oh) > cap:
            scale = cap / float(max(ow, oh))
            rgb = rgb.resize((max(1, int(ow * scale)), max(1, int(oh * scale))))
        arr = np.asarray(rgb, dtype=np.uint8)
    return arr, ow, oh


class DecodePool:
    """A recycled ProcessPool that decodes image bytes -> (uint8 RGB array, w, h).

    The returned width/height are the *original* dimensions (so salience still
    sees the true size even when the array is downscaled to `cap` for cheap IPC).
    """

    def __init__(self, workers=2, recycle=200, cap=1024, timeout=8.0):
        self.workers = max(1, int(workers))
        self.recycle = max(1, int(recycle))
        self.cap = int(cap)
        self.timeout = float(timeout)
        self._pool = self._new_pool()

    def _new_pool(self):
        return ProcessPoolExecutor(max_workers=self.workers,
                                   max_tasks_per_child=self.recycle)

    def decode(self, raw):
        try:
            return self._pool.submit(_decode, raw, self.cap).result(timeout=self.timeout)
        except BrokenProcessPool:
            # A worker died (e.g. a decoder segfault). Rebuild so later requests
            # recover; this one fails (caller treats it as a transient error).
            self._pool = self._new_pool()
            raise

    def close(self):
        self._pool.shutdown(wait=False)
