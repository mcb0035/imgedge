"""AppContainer feasibility spike (feature/sandbox, Windows only).

Unlike the Low-integrity drop, an AppContainer cannot be entered by a running
process — it must be applied at CreateProcess time via SECURITY_CAPABILITIES.
So this can't ride on ProcessPoolExecutor; it's a separate launcher.

`demo()` proves the crux before any productionising:
  1. create/derive an AppContainer SID,
  2. grant it read/execute on the Python install + venv (AppContainers see an
     isolated FS view and can't read user files unless explicitly granted),
  3. launch a probe **inside** the container with NO capabilities (no network),
  4. the probe imports Pillow/numpy, decodes an in-memory image, and tries a
     network connection — proving decode works and network is denied.

Run:  python -m imgedge.classifier.appcontainer
Grants are reversible:  icacls <path> /remove:g *<sid>
"""

import ctypes
import subprocess
import sys
import sysconfig
import time
from ctypes import wintypes
from pathlib import Path

_userenv = ctypes.WinDLL("userenv", use_last_error=True)
_adv = ctypes.WinDLL("advapi32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

_PROFILE_NAME = "imgedge.decode.sandbox"
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_NO_WINDOW = 0x08000000
_ERROR_ALREADY_EXISTS = 0x800700B7  # HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS)


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class _SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [("AppContainerSid", ctypes.c_void_p), ("Capabilities", ctypes.c_void_p),
                ("CapabilityCount", wintypes.DWORD), ("Reserved", wintypes.DWORD)]


_userenv.CreateAppContainerProfile.restype = ctypes.c_long
_userenv.CreateAppContainerProfile.argtypes = [
    wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
_userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
_userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
    wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
_adv.ConvertSidToStringSidW.restype = wintypes.BOOL
_adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]


def ensure_sid():
    """Create (or derive if it exists) the AppContainer SID. Returns (psid, str)."""
    sid = ctypes.c_void_p()
    hr = _userenv.CreateAppContainerProfile(
        _PROFILE_NAME, _PROFILE_NAME, "ImgEdge decode sandbox",
        None, 0, ctypes.byref(sid))
    if hr != 0 and (hr & 0xFFFFFFFF) == _ERROR_ALREADY_EXISTS:
        if _userenv.DeriveAppContainerSidFromAppContainerName(
                _PROFILE_NAME, ctypes.byref(sid)) != 0:
            raise OSError("DeriveAppContainerSidFromAppContainerName failed")
    elif hr != 0:
        raise OSError(f"CreateAppContainerProfile failed: 0x{hr & 0xFFFFFFFF:08x}")
    s = wintypes.LPWSTR()
    if not _adv.ConvertSidToStringSidW(sid, ctypes.byref(s)):
        raise ctypes.WinError(ctypes.get_last_error())
    return sid, s.value


def grant(path, sid_str, perm="(RX)"):
    """Grant the AppContainer SID `perm` on `path` (recursive) via icacls."""
    r = subprocess.run(
        ["icacls", str(path), "/grant", f"*{sid_str}:(OI)(CI){perm}", "/T", "/C", "/Q"],
        capture_output=True, text=True)
    return r.returncode == 0


def launch(cmdline, sid, cwd, timeout_s=60):
    """CreateProcess `cmdline` inside the AppContainer (no capabilities). Returns exit code."""
    size = ctypes.c_size_t(0)
    _k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    buf = (ctypes.c_byte * size.value)()
    if not _k32.InitializeProcThreadAttributeList(buf, 1, 0, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    caps = _SECURITY_CAPABILITIES(AppContainerSid=sid, Capabilities=None,
                                  CapabilityCount=0, Reserved=0)
    if not _k32.UpdateProcThreadAttribute(
            buf, 0, _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            ctypes.byref(caps), ctypes.sizeof(caps), None, None):
        raise ctypes.WinError(ctypes.get_last_error())
    si = _STARTUPINFOEXW()
    si.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
    si.lpAttributeList = ctypes.cast(buf, ctypes.c_void_p)
    pi = _PROCESS_INFORMATION()
    cmd = ctypes.create_unicode_buffer(cmdline)
    ok = _k32.CreateProcessW(
        None, cmd, None, None, False,
        _EXTENDED_STARTUPINFO_PRESENT | _CREATE_NO_WINDOW,
        None, str(cwd), ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    _k32.WaitForSingleObject(pi.hProcess, int(timeout_s * 1000))
    code = wintypes.DWORD()
    _k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    _k32.CloseHandle(pi.hProcess)
    _k32.CloseHandle(pi.hThread)
    _k32.DeleteProcThreadAttributeList(buf)
    return code.value


_PROBE = r'''
import sys, io, base64
out = sys.argv[1]
log = []
def w(m): log.append(str(m))
try:
    import ctypes
    from imgedge.classifier import confine
    w("integrity=" + confine.current_integrity())
except Exception as e:
    w("integrity_err=" + repr(e))
try:
    import socket
    s = socket.socket(); s.settimeout(3); s.connect(("1.1.1.1", 80)); s.close()
    w("network=ALLOWED")
except Exception as e:
    w("network=DENIED:" + type(e).__name__)
try:
    import numpy as np
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 24_000_000
    px = base64.b64decode("PNG_B64")
    with Image.open(io.BytesIO(px), formats=["JPEG","PNG","WEBP","GIF","BMP"]) as im:
        a = np.asarray(im.convert("RGB"), dtype="uint8")
    w("decode=OK shape=" + str(a.shape))
except Exception as e:
    w("decode_err=" + repr(e))
try:
    open(r"PROBE_WRITE_TEST", "w").close()
    w("write_user_dir=ALLOWED")
except Exception as e:
    w("write_user_dir=DENIED:" + type(e).__name__)
open(out, "w", encoding="utf-8").write("\n".join(log))
'''


def _png_b64():
    import base64
    import io

    import numpy as np
    from PIL import Image
    b = io.BytesIO()
    arr = (np.random.default_rng(0).random((8, 8, 3)) * 255).astype("uint8")
    Image.fromarray(arr).save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def demo():
    if sys.platform != "win32":
        print("AppContainer is Windows-only")
        return
    py = Path(sys.executable)
    base = Path(sysconfig.get_paths()["stdlib"]).parent  # base interpreter dir
    venv = Path(sys.prefix)
    shared = Path.home() / ".imgedge-ac"
    shared.mkdir(exist_ok=True)
    probe = shared / "probe.py"
    status = shared / "status.txt"
    write_test = Path.home() / "imgedge_ac_WRITE_TEST.txt"  # a medium-IL path NOT granted
    code = _PROBE.replace("PROBE_WRITE_TEST", str(write_test).replace("\\", "\\\\"))
    code = code.replace("PNG_B64", _png_b64())
    probe.write_text(code, encoding="utf-8")
    if status.exists():
        status.unlink()

    sid, sid_str = ensure_sid()
    print("AppContainer SID:", sid_str)
    if "--skip-grant" not in sys.argv:
        print("granting read/execute to the container (this can take a moment)...")
        t0 = time.perf_counter()
        grant(base, sid_str, "(RX)")
        grant(venv, sid_str, "(RX)")
        grant(shared, sid_str, "(M)")  # the one dir it may write
        print(f"  grants done in {time.perf_counter() - t0:.1f}s")

    cmd = f'"{py}" "{probe}" "{status}"'
    print("launching probe inside the AppContainer...")
    t0 = time.perf_counter()
    rc = launch(cmd, sid, shared, timeout_s=60)
    dt = (time.perf_counter() - t0) * 1000
    print(f"  exit={rc}  wall={dt:.0f}ms")
    print("--- probe report ---")
    print(status.read_text(encoding="utf-8") if status.exists() else "(no status written)")


if __name__ == "__main__":
    demo()
