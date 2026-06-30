"""Performance-regression guards (the CI 'perf' job; ``pytest -m perf``).

Deliberately RELATIVE / invariant checks rather than absolute-millisecond
thresholds: shared CI runners vary several-fold run to run, so an absolute gate
would be flaky. Each test measures a baseline and the thing under test in the
SAME run and asserts an invariant with a generous margin -- enough to catch the
regressions that matter (a "warm" pool silently spawning/importing per call, IPC
blowing up, or the BLAS thread-cap being dropped) while tolerating noise.
"""

import io
import os
import statistics
import sys
import time
from functools import partial

import numpy as np
import pytest
from PIL import Image

pytestmark = pytest.mark.perf


def _png(side):
    buf = io.BytesIO()
    arr = (np.random.default_rng(0).random((side, side, 3)) * 255).astype("uint8")
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def _median_ms(fn, raw, iters=15, warm=3):
    for _ in range(warm):
        fn(raw)
    ts = []
    for _ in range(iters):
        t = time.perf_counter()
        fn(raw)
        ts.append((time.perf_counter() - t) * 1000)
    return statistics.median(ts)


def test_pool_stays_warm():
    """Steady-state decode must be far cheaper than the first (cold) decode, which
    pays the worker's one-time numpy/Pillow import. If the pool regressed to
    importing/spawning per call, warm ~= cold and this fails."""
    from imgedge.classifier.decode_pool import DecodePool

    raw = _png(128)
    pool = DecodePool(workers=1)
    try:
        t = time.perf_counter()
        pool.decode(raw)  # cold: first import in worker
        cold_ms = (time.perf_counter() - t) * 1000
        warm_ms = _median_ms(pool.decode, raw)
    finally:
        pool.close()
    assert warm_ms * 5 < cold_ms, f"no warm reuse: warm={warm_ms:.1f}ms cold={cold_ms:.1f}ms"


def test_warm_ipc_overhead_bounded():
    """Out-of-process decode only adds the pipe round-trip over in-process; guard
    against a gross IPC/serialization regression with a generous bound."""
    from imgedge.classifier.decode_pool import DecodePool, _decode

    raw = _png(256)
    inproc_ms = _median_ms(partial(_decode, cap=1024), raw)
    pool = DecodePool(workers=1)
    try:
        pool.decode(raw)  # warm
        pool_ms = _median_ms(pool.decode, raw)
    finally:
        pool.close()
    assert pool_ms < inproc_ms * 5 + 10, f"pool={pool_ms:.1f}ms inproc={inproc_ms:.1f}ms"


@pytest.mark.skipif(
    "OPENBLAS_NUM_THREADS" in os.environ or "OMP_NUM_THREADS" in os.environ,
    reason="parent env overrides BLAS/OMP thread count",
)
def test_worker_caps_blas_threads():
    """Decode workers must run with OPENBLAS/OMP_NUM_THREADS=1 -- decode does no
    BLAS, and without the cap numpy/OpenBLAS reserves ~hundreds of MB of commit
    per worker. Verifies the cap is applied inside the live worker."""
    from imgedge.classifier.decode_pool import DecodePool, _env_probe

    pool = DecodePool(workers=1)
    try:
        pool.decode(_png(64))  # ensure a worker is up
        threads = pool._pool.submit(_env_probe).result(timeout=15)
    finally:
        pool.close()
    assert threads == ("1", "1"), f"worker BLAS threads not capped: {threads}"


@pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("IMGEDGE_TEST_APPCONTAINER") != "1",
    reason="AppContainer perf test is Windows-only and opt-in (IMGEDGE_TEST_APPCONTAINER=1)",
)
def test_appcontainer_stays_warm():
    """The AppContainer pool must keep workers warm: a per-call container spawn
    (~150 ms) would be catastrophic. Steady-state decode must sit far below the
    pool's construction time (which pays the spawn)."""
    from imgedge.classifier.ac_pool import AppContainerPool

    raw = _png(128)
    t = time.perf_counter()
    pool = AppContainerPool(workers=1)
    build_ms = (time.perf_counter() - t) * 1000  # includes the worker spawn
    try:
        warm_ms = _median_ms(pool.decode, raw)
    finally:
        pool.close()
    assert warm_ms * 10 < build_ms, f"per-call spawn? warm={warm_ms:.1f}ms build={build_ms:.1f}ms"
