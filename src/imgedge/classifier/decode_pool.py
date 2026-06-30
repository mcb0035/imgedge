"""Optional out-of-process image decode (prototype, feature/sandbox).

Runs the memory-unsafe part — the Pillow format decode in ``open_guarded`` — in a
recycled worker pool, and returns only a trusted uint8 RGB array to the parent.
A crash/exploit in a decoder is then contained to a child process (the pool
replaces it), and workers are recycled every N tasks to bound how long any
compromised worker lives.

IMPORTANT: this is a CRASH + RECYCLE boundary, not an OS sandbox. The children
are ordinary processes (no seccomp / namespaces on Linux), so a decoder exploit
could still do what the user can. For true OS confinement on Windows, the
AppContainer pool (``ac_pool.py``, ``IMGEDGE_SANDBOX_APPCONTAINER=1``) also
denies the worker network access and writes to the user's files; this pool
remains the cross-platform crash boundary. Enable with IMGEDGE_SANDBOX=1.
"""

from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from imgedge.classifier import confine


def _decode(raw, cap):
    # numpy/Pillow are imported here (not at module top) so the parent needn't
    # load them, and so worker_init's OPENBLAS_NUM_THREADS=1 takes effect before
    # numpy/OpenBLAS initialises.
    import numpy as np

    from imgedge.inat.inat_filter import open_guarded

    with open_guarded(raw) as img:
        rgb = img.convert("RGB")
        ow, oh = rgb.size
        if cap and max(ow, oh) > cap:
            scale = cap / float(max(ow, oh))
            rgb = rgb.resize((max(1, int(ow * scale)), max(1, int(oh * scale))))
        arr = np.asarray(rgb, dtype=np.uint8)
    return arr, ow, oh


def _ping():
    return True


def _integrity_probe():
    from imgedge.classifier import confine

    return confine.current_integrity()


def _env_probe():
    """Report the worker's BLAS/OMP thread caps (used by the perf-regression tests)."""
    import os

    return os.environ.get("OPENBLAS_NUM_THREADS"), os.environ.get("OMP_NUM_THREADS")


class DecodePool:
    """A recycled ProcessPool that decodes image bytes -> (uint8 RGB array, w, h).

    The returned width/height are the *original* dimensions (so salience still
    sees the true size even when the array is downscaled to `cap` for cheap IPC).
    """

    kind = "process"

    def __init__(
        self,
        workers=2,
        recycle=200,
        cap=1024,
        timeout=8.0,
        confine_os=True,
        mem_mb=1024,
        low_il=False,
    ):
        self.workers = max(1, int(workers))
        self.recycle = max(1, int(recycle))
        self.cap = int(cap)
        self.timeout = float(timeout)
        self.mem_bytes = int(mem_mb) * 1024 * 1024
        self.low_il = bool(low_il)
        self._job = None
        if confine_os and confine.WindowsJob is not None:
            try:
                self._job = confine.WindowsJob(self.mem_bytes, self.workers + 2)
            except OSError:
                self._job = None  # confinement is best-effort; never block decoding
        self._assigned = set()
        self._pool = self._new_pool()
        self._confine_workers()  # spawn + assign before real traffic

    def _new_pool(self):
        return ProcessPoolExecutor(
            max_workers=self.workers,
            max_tasks_per_child=self.recycle,
            initializer=confine.worker_init,
            initargs=(self.mem_bytes, self.low_il),
        )

    def _assign_new(self):
        """Assign any not-yet-confined worker PIDs to the Job (cheap; no IPC)."""
        if self._job is None:
            return
        for pid in list(getattr(self._pool, "_processes", {}) or {}):
            if pid not in self._assigned and self._job.assign(pid):
                self._assigned.add(pid)

    def _confine_workers(self):
        if self._job is None:
            return
        try:
            self._pool.submit(_ping).result(timeout=self.timeout)  # force initial spawn
        except Exception:
            pass  # best-effort
        self._assign_new()

    @property
    def confined(self):
        return self._job is not None

    def worker_integrity(self):
        """Probe a worker's integrity level (e.g. 'low') for verification."""
        try:
            return self._pool.submit(_integrity_probe).result(timeout=self.timeout)
        except Exception:
            return "?"

    def decode(self, raw):
        self._assign_new()  # confine recycled / new workers (no extra round-trip)
        try:
            return self._pool.submit(_decode, raw, self.cap).result(timeout=self.timeout)
        except BrokenProcessPool:
            # A worker died (decoder segfault, or a Job memory-limit kill). Rebuild
            # so later requests recover; this one fails (transient error).
            self._assigned.clear()
            self._pool = self._new_pool()
            self._confine_workers()
            raise

    def close(self):
        self._pool.shutdown(wait=False)
        if self._job is not None:
            self._job.close()  # KILL_ON_JOB_CLOSE reaps any survivors
