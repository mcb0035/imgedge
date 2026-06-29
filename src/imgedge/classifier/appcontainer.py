"""AppContainer launch primitives (feature/sandbox, Windows only).

An AppContainer cannot be entered by a running process -- it must be applied at
CreateProcess time via SECURITY_CAPABILITIES -- so it can't ride on
ProcessPoolExecutor. This module holds the low-level pieces the warm decode pool
(ac_pool.py) builds on:

  * ensure_sid()      create/derive the per-app AppContainer SID,
  * grant()           icacls read/execute for that SID on a path (an AppContainer
                      sees an isolated FS view and can't read paths not granted),
  * spawn()/launch()  CreateProcess a command *inside* the container with NO
                      capabilities (no network, no write to the user's files),
                      inheriting only an explicit handle list (+ NUL stdio).

`demo()` (python -m imgedge.classifier.appcontainer) is a standalone check that
decode works while network + user-file writes are denied.
Grants are reversible:  icacls <path> /remove:g *<sid>
"""

import ctypes
import subprocess
import sys
from ctypes import wintypes

_userenv = ctypes.WinDLL("userenv", use_last_error=True)
_adv = ctypes.WinDLL("advapi32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

_PROFILE_NAME = "imgedge.decode.sandbox"
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
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
    """Grant the AppContainer SID `perm` on `path`'s whole subtree via an
    INHERITABLE ACE on the root -- no `/T` tree-walk. NTFS propagates the
    inheritable ACE to existing descendants, so a large venv (e.g. with torch) is
    granted in milliseconds instead of minutes. (A child with a protected ACL
    would be missed; that doesn't occur in a normal pip venv.)"""
    r = subprocess.run(
        ["icacls", str(path), "/grant", f"*{sid_str}:(OI)(CI){perm}", "/C", "/Q"],
        capture_output=True, text=True)
    return r.returncode == 0


_STARTF_USESTDHANDLES = 0x00000100
_GENERIC_RW = 0xC0000000
_FILE_SHARE_RW = 0x00000003
_OPEN_EXISTING = 3
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]


def spawn(cmdline, sid, cwd, inherit_handles=None):
    """CreateProcess `cmdline` inside the AppContainer (no capabilities -> no
    network and no write access to the user's files). If `inherit_handles` is
    given, *exactly* those handles (plus an inheritable NUL for the child's
    stdio) are inherited via a HANDLE_LIST, so no stray parent handle (a console,
    a writable file, a socket) can leak into the sandbox -- an inherited writable
    handle would otherwise bypass the AppContainer's write-deny. Returns
    PROCESS_INFORMATION; the caller owns and must close hProcess/hThread.
    """
    nattr = 2 if inherit_handles else 1
    size = ctypes.c_size_t(0)
    _k32.InitializeProcThreadAttributeList(None, nattr, 0, ctypes.byref(size))
    buf = (ctypes.c_byte * size.value)()
    if not _k32.InitializeProcThreadAttributeList(buf, nattr, 0, ctypes.byref(size)):
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
    nul = None
    harr = None  # keep the handle array alive until after CreateProcess
    if inherit_handles:
        sa = _SECURITY_ATTRIBUTES(nLength=ctypes.sizeof(_SECURITY_ATTRIBUTES),
                                  lpSecurityDescriptor=None, bInheritHandle=True)
        nul = _k32.CreateFileW("NUL", _GENERIC_RW, _FILE_SHARE_RW, ctypes.byref(sa),
                               _OPEN_EXISTING, 0, None)
        if not nul or nul == _INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        si.StartupInfo.dwFlags |= _STARTF_USESTDHANDLES
        si.StartupInfo.hStdInput = nul
        si.StartupInfo.hStdOutput = nul
        si.StartupInfo.hStdError = nul
        all_h = list(inherit_handles) + [nul]
        harr = (wintypes.HANDLE * len(all_h))(*[wintypes.HANDLE(h) for h in all_h])
        if not _k32.UpdateProcThreadAttribute(
                buf, 0, _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                harr, ctypes.sizeof(harr), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
    pi = _PROCESS_INFORMATION()
    cmd = ctypes.create_unicode_buffer(cmdline)
    ok = _k32.CreateProcessW(
        None, cmd, None, None, bool(inherit_handles),
        _EXTENDED_STARTUPINFO_PRESENT | _CREATE_NO_WINDOW,
        None, str(cwd), ctypes.byref(si), ctypes.byref(pi))
    err = ctypes.get_last_error()
    _k32.DeleteProcThreadAttributeList(buf)
    if nul:
        _k32.CloseHandle(wintypes.HANDLE(nul))
    if not ok:
        raise ctypes.WinError(err)
    return pi


def launch(cmdline, sid, cwd, timeout_s=60):
    """Spawn inside the AppContainer, wait up to `timeout_s`, return exit code."""
    pi = spawn(cmdline, sid, cwd)
    _k32.WaitForSingleObject(pi.hProcess, int(timeout_s * 1000))
    code = wintypes.DWORD()
    _k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    _k32.CloseHandle(pi.hProcess)
    _k32.CloseHandle(pi.hThread)
    return code.value


def demo():
    """Standalone check: decode works, but network + user-file writes are denied.

    Builds a one-worker AppContainerPool (which performs the cached icacls grant)
    and prints its decode result and isolation probe -- the very code the server
    uses, so there is no separate, divergeable probe to maintain.
    """
    if sys.platform != "win32":
        print("AppContainer is Windows-only")
        return
    import io

    import numpy as np
    from PIL import Image

    from imgedge.classifier.ac_pool import AppContainerPool

    buf = io.BytesIO()
    Image.fromarray(
        (np.random.default_rng(0).random((16, 16, 3)) * 255).astype("uint8")).save(buf, "PNG")
    pool = AppContainerPool(workers=1, recycle=10)
    try:
        arr, ow, oh = pool.decode(buf.getvalue())
        print(f"decode:    OK shape={arr.shape} original=({ow}, {oh})")
        print(f"isolation: {pool.probe()}")
        print(f"confined:  {pool.confined} (Job object)")
    finally:
        pool.close()


if __name__ == "__main__":
    demo()
