"""Production AppContainer decode pool (feature/sandbox, Windows only).

Decodes image bytes inside warm, prespawned AppContainer worker processes that
run with NO capabilities: a decoder exploit cannot open a socket (network is
denied) or write the user's files, yet decoding still works because Pillow/numpy
and the imgedge source are granted *read* access to the Python install + venv.

Design (mirrors DecodePool's interface so the server/ensemble are unchanged):
  * N warm workers, each launched once into the AppContainer and kept alive.
  * IPC over inherited anonymous pipes (AppContainer denies loopback sockets, so
    pipes are the only faithful channel); only the two pipe ends are inherited
    (HANDLE_LIST), never a stray parent handle.
  * Each worker is recycled after `recycle` decodes (bounds how long any single,
    possibly-compromised worker lives) and self-heals if it dies.
  * A per-call watchdog kills a worker that exceeds `timeout` (hang protection).
  * A Job object caps each worker's committed memory and reaps survivors on close.

First use performs a one-time `icacls` grant of the AppContainer SID on the
Python install + venv + imgedge source (an inheritable ACE on each root, so even
a torch-heavy venv is granted in milliseconds, not a `/T` tree-walk); it is
cached (a marker file + an ACL check) so later starts skip it entirely.
"""

import base64
import ctypes
import json
import msvcrt
import os
import struct
import subprocess
import sys
import threading
from ctypes import wintypes
from pathlib import Path

import numpy as np

from imgedge.classifier import appcontainer as ac
from imgedge.classifier import confine

_k32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None
_HANDLE_FLAG_INHERIT = 1
_STILL_ACTIVE = 259

if _k32 is not None:
    _k32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _k32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]


# Decode loop that runs *inside* each AppContainer worker. It reuses the same
# open_guarded hardening as the in-process path (single source of truth), so the
# format allow-list and pixel cap can never silently diverge.
_WORKER = r"""
import os, sys, struct, msvcrt, traceback
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')  # decode does no BLAS
os.environ.setdefault('OMP_NUM_THREADS', '1')
rfd = msvcrt.open_osfhandle(int(sys.argv[2]), os.O_RDONLY | os.O_BINARY)
wfd = msvcrt.open_osfhandle(int(sys.argv[3]), os.O_WRONLY | os.O_BINARY)
cap = int(sys.argv[4])
def frame(d):
    mv = memoryview(struct.pack('>I', len(d)) + d)
    while mv:
        mv = mv[os.write(wfd, mv):]
try:
    import numpy as np
    from imgedge.inat.inat_filter import open_guarded
except BaseException:
    frame(b'X' + traceback.format_exc().encode())
    os._exit(1)
def readn(n):
    b = b''
    while len(b) < n:
        c = os.read(rfd, n - len(b))
        if not c:
            os._exit(0)
        b += c
    return b
frame(b'RDY')
while True:
    n = struct.unpack('>I', readn(4))[0]
    if n == 0:
        break
    buf = readn(n)
    op, payload = buf[:1], buf[1:]
    if op == b'D':
        try:
            with open_guarded(payload) as img:
                rgb = img.convert('RGB')
                ow, oh = rgb.size
                if cap and max(ow, oh) > cap:
                    s = cap / float(max(ow, oh))
                    rgb = rgb.resize((max(1, int(ow * s)), max(1, int(oh * s))))
                a = np.asarray(rgb, dtype=np.uint8)
            frame(b'K' + struct.pack('>IIIII', a.shape[0], a.shape[1], 3, ow, oh)
                  + a.tobytes())
        except Exception:
            frame(b'E' + traceback.format_exc().encode())
    elif op == b'P':
        rep = []
        try:
            import socket
            s = socket.socket(); s.settimeout(2); s.connect(('1.1.1.1', 80)); s.close()
            rep.append('network=ALLOWED')
        except Exception as e:
            rep.append('network=DENIED:' + type(e).__name__)
        try:
            p = os.path.join(os.path.expanduser('~'), '.imgedge-ac-wtest')
            open(p, 'w').close(); os.remove(p); rep.append('write=ALLOWED')
        except Exception as e:
            rep.append('write=DENIED:' + type(e).__name__)
        frame(b'P' + '\n'.join(rep).encode())
"""


class _SA(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSD", ctypes.c_void_p), ("bInherit", wintypes.BOOL)]


def _pipe(inherit_read, inherit_write, bufsize):
    r, w = wintypes.HANDLE(), wintypes.HANDLE()
    sa = _SA(ctypes.sizeof(_SA), None, True)
    if not _k32.CreatePipe(ctypes.byref(r), ctypes.byref(w), ctypes.byref(sa), bufsize):
        raise ctypes.WinError(ctypes.get_last_error())
    if not inherit_read:
        _k32.SetHandleInformation(r, _HANDLE_FLAG_INHERIT, 0)
    if not inherit_write:
        _k32.SetHandleInformation(w, _HANDLE_FLAG_INHERIT, 0)
    return r.value, w.value


def _readn(fd, n):
    b = b""
    while len(b) < n:
        c = os.read(fd, n - len(b))
        if not c:
            raise EOFError("worker closed pipe")
        b += c
    return b


def _writeall(fd, data):
    mv = memoryview(data)
    while mv:
        mv = mv[os.write(fd, mv) :]


def _grant_targets():
    """Dirs the AppContainer SID needs *read* on: Python install, venv, imgedge src."""
    targets, seen = [], set()
    import imgedge

    for p in (Path(sys.base_prefix), Path(sys.prefix), Path(imgedge.__file__).resolve().parents[1]):
        rp = str(p)
        if p.exists() and rp not in seen:
            seen.add(rp)
            targets.append(p)
    return targets


def _is_granted(path, sid_str):
    """Fast check: does `path`'s ACL already mention our SID / profile?"""
    try:
        out = subprocess.run(["icacls", str(path)], capture_output=True, text=True, timeout=20).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False
    return sid_str.lower() in out or ac._PROFILE_NAME.lower() in out


def _ensure_grants(sid_str):
    """One-time (cached) icacls grant of the SID on the Python/venv/src trees."""
    marker = Path.home() / ".imgedge-ac" / "grants.json"
    try:
        done = json.loads(marker.read_text("utf-8")).get(sid_str, [])
    except (OSError, ValueError):
        done = []
    changed = False
    for t in _grant_targets():
        key = str(t)
        if key in done:
            continue
        if _is_granted(t, sid_str) or ac.grant(t, sid_str):  # ACL check, else grant (inheritable)
            done.append(key)
            changed = True
    if changed:
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if marker.exists():
                data = json.loads(marker.read_text("utf-8"))
            data[sid_str] = done
            marker.write_text(json.dumps(data), "utf-8")
        except (OSError, ValueError):
            pass  # marker is only an optimisation; never block on it


class _Worker:
    __slots__ = ("pi", "pw", "pr", "tasks")

    def __init__(self, pi, pw, pr):
        self.pi = pi
        self.pw = pw
        self.pr = pr
        self.tasks = 0


class AppContainerPool:
    """Warm AppContainer decode pool: decode(raw) -> (uint8 RGB array, ow, oh)."""

    kind = "appcontainer"

    def __init__(self, workers=2, recycle=200, cap=1024, timeout=8.0, mem_mb=1024, confine_os=True):
        if sys.platform != "win32":
            raise OSError("AppContainerPool requires Windows")
        self.workers = max(1, int(workers))
        self.recycle = max(1, int(recycle))
        self.cap = int(cap)
        self.timeout = float(timeout)
        self.mem_bytes = int(mem_mb) * 1024 * 1024
        self._lock = threading.Lock()
        self._sid, self._sid_str = ac.ensure_sid()
        _ensure_grants(self._sid_str)
        self._b64 = base64.b64encode(_WORKER.encode()).decode()
        self._job = None
        if confine_os and confine.WindowsJob is not None:
            try:
                self._job = confine.WindowsJob(self.mem_bytes, self.workers + 2)
            except OSError:
                self._job = None  # confinement is best-effort; never block decoding
        self._pool = [self._spawn() for _ in range(self.workers)]
        self._rr = 0

    # -- worker lifecycle --------------------------------------------------
    def _spawn(self):
        req_r, req_w = _pipe(inherit_read=True, inherit_write=False, bufsize=16 << 20)
        resp_r, resp_w = _pipe(inherit_read=False, inherit_write=True, bufsize=16 << 20)
        boot = "import base64,sys;exec(base64.b64decode(sys.argv[1]).decode())"
        cmd = f'"{sys.executable}" -c "{boot}" {self._b64} {req_r} {resp_w} {self.cap}'
        try:
            pi = ac.spawn(cmd, self._sid, os.getcwd(), inherit_handles=[req_r, resp_w])
        finally:
            _k32.CloseHandle(wintypes.HANDLE(req_r))  # child has its own copies now
            _k32.CloseHandle(wintypes.HANDLE(resp_w))
        if self._job is not None:
            self._job.assign(pi.dwProcessId)
        wk = _Worker(
            pi,
            msvcrt.open_osfhandle(req_w, os.O_WRONLY | os.O_BINARY),
            msvcrt.open_osfhandle(resp_r, os.O_RDONLY | os.O_BINARY),
        )
        try:
            first = self._read_frame(wk)
        except (EOFError, OSError):
            first = b""
        if first != b"RDY":
            code = wintypes.DWORD()
            _k32.GetExitCodeProcess(wk.pi.hProcess, ctypes.byref(code))
            self._close_worker(wk)
            detail = (
                first[1:].decode("utf-8", "replace")[:600]
                if first[:1] == b"X"
                else f"exit=0x{code.value & 0xFFFFFFFF:08x} frame={first[:40]!r}"
            )
            raise OSError("AppContainer worker failed to start: " + detail)
        return wk

    def _read_frame(self, wk):
        """Read one length-prefixed frame; kill the worker if it exceeds timeout."""
        timer = threading.Timer(self.timeout, self._kill, args=(wk,))
        timer.start()
        try:
            return _readn(wk.pr, struct.unpack(">I", _readn(wk.pr, 4))[0])
        finally:
            timer.cancel()

    def _kill(self, wk):
        try:
            _k32.TerminateProcess(wk.pi.hProcess, 1)
        except OSError:
            pass

    def _alive(self, wk):
        code = wintypes.DWORD()
        if not _k32.GetExitCodeProcess(wk.pi.hProcess, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE

    def _close_worker(self, wk):
        for fd in (wk.pw, wk.pr):
            try:
                os.close(fd)
            except OSError:
                pass
        self._kill(wk)
        _k32.CloseHandle(wk.pi.hProcess)
        _k32.CloseHandle(wk.pi.hThread)

    def _replace(self, wk):
        try:
            i = self._pool.index(wk)
        except ValueError:
            i = None
        self._close_worker(wk)
        new = self._spawn()
        if i is not None:
            self._pool[i] = new
        return new

    def _checkout(self):
        wk = self._pool[self._rr % len(self._pool)]
        self._rr += 1
        if not self._alive(wk):
            wk = self._replace(wk)
        return wk

    # -- public interface (matches DecodePool) -----------------------------
    @property
    def confined(self):
        return self._job is not None

    def worker_integrity(self):
        return "appcontainer"

    def decode(self, raw):
        with self._lock:
            wk = self._checkout()
            try:
                _writeall(wk.pw, struct.pack(">I", len(raw) + 1) + b"D" + raw)
                fr = self._read_frame(wk)
            except (OSError, EOFError) as e:
                self._replace(wk)  # worker died / timed out -> heal for next call
                raise RuntimeError("decode worker died") from e
            wk.tasks += 1
            if wk.tasks >= self.recycle:
                self._replace(wk)
            if not fr or fr[:1] != b"K":
                detail = fr[1:].decode("utf-8", "replace")[:400] if fr else "empty"
                raise RuntimeError("decode failed: " + detail)
            h, w, c, ow, oh = struct.unpack(">IIIII", fr[1:21])
            arr = np.frombuffer(fr[21 : 21 + h * w * c], dtype=np.uint8).reshape(h, w, c)
            return arr, ow, oh

    def probe(self):
        """Ask a worker to attempt network + a user-file write (for verification)."""
        with self._lock:
            wk = self._checkout()
            try:
                _writeall(wk.pw, struct.pack(">I", 1) + b"P")
                fr = self._read_frame(wk)
            except (OSError, EOFError):
                self._replace(wk)
                return {}
        out = {}
        for part in fr[1:].decode("utf-8", "replace").split("\n"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k] = v
        return out

    def close(self):
        with self._lock:
            for wk in self._pool:
                try:
                    _writeall(wk.pw, struct.pack(">I", 0))  # graceful shutdown
                except OSError:
                    pass
            for wk in self._pool:
                self._close_worker(wk)
            self._pool = []
            if self._job is not None:
                self._job.close()  # KILL_ON_JOB_CLOSE reaps any survivors
