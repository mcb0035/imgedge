# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Resident memory footprint of the server + decode workers (Windows).

Run from the repo root with the project venv:
    python benchmark/footprint.py

Prints `working-set / private-commit` (MB) for the parent and each decode worker,
then the parent with the full model ensemble loaded. numpy is imported lazily so
the pool workers' OPENBLAS_NUM_THREADS=1 cap is measured faithfully.
"""

import ctypes
import io
import os
import sys
from ctypes import wintypes

os.environ.setdefault("IMGEDGE_LOG_FILE", "none")
os.environ.setdefault("IMGEDGE_CACHE_FILE", "none")


class _PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


if sys.platform == "win32":
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ps = ctypes.WinDLL("psapi")
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]


def _mb(handle):
    """working-set / private-commit MB for an already-open process handle."""
    c = _PMC()
    c.cb = ctypes.sizeof(c)
    ok = _ps.GetProcessMemoryInfo(wintypes.HANDLE(handle), ctypes.byref(c), c.cb)
    return f"{c.WorkingSetSize // 1048576}/{c.PagefileUsage // 1048576}" if ok else "?/?"


def _pid_mb(pid):
    h = _k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return "?/?"
    try:
        return _mb(h)
    finally:
        _k32.CloseHandle(wintypes.HANDLE(h))


def _jpeg(side):
    import numpy as np
    from PIL import Image

    buf = io.BytesIO()
    arr = (np.random.default_rng(0).random((side, side, 3)) * 255).astype("uint8")
    Image.fromarray(arr).save(buf, "JPEG", quality=85)
    return buf.getvalue()


def main():
    if sys.platform != "win32":
        print("footprint.py reads Win32 process counters; run it on Windows.")
        return
    raw = _jpeg(512)
    me = os.getpid()
    print("(working-set / private-commit MB)\n")
    print(f"parent, numpy+PIL only:      {_pid_mb(me)}")

    from imgedge.classifier.decode_pool import DecodePool

    dp = DecodePool(workers=2)
    dp.decode(raw)
    pids = list(getattr(dp._pool, "_processes", {}) or {})
    print(f"DecodePool worker(s):        {[_pid_mb(p) for p in pids]}")
    dp.close()

    from imgedge.classifier.ac_pool import AppContainerPool

    ap = AppContainerPool(workers=2)
    ap.decode(raw)
    print(f"AppContainer workers:        {[_mb(wk.pi.hProcess) for wk in ap._pool]}")
    ap.close()

    try:
        from imgedge.classifier import server

        server.ensure_ensemble()
        print(f"parent WITH model ensemble:  {_pid_mb(me)}")
    except Exception as e:  # model files may be absent
        print("ensemble load skipped:", type(e).__name__, str(e)[:100])


if __name__ == "__main__":
    main()
