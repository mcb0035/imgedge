"""OS-level confinement for decode workers (feature/sandbox).

Windows: the workers are placed in a Job object that caps total committed memory
(beyond the pixel guard, this stops a decompression bomb), limits the active
process count (no fork bombs from a compromised decoder), restricts UI access
(clipboard / global atoms / handles / desktop / exit-windows), dies on an
unhandled exception, and kills every worker when the server exits.

POSIX: each worker self-limits its address space via ``setrlimit``.

NOTE — what this is and isn't: this is kernel-enforced *resource + UI + lifecycle*
confinement, which bounds abuse and contains crashes. It is **not** a full
privilege drop: a code-exec exploit in a decoder could still read files the user
can read or make network calls. The stronger follow-ups are a low-integrity /
restricted token or an AppContainer (Windows) and seccomp/namespaces (Linux);
those need extra setup (e.g. granting the container read access to the venv) and
are intentionally left as the next step.
"""

import sys


def worker_init(mem_bytes, low_il=True):
    """Run inside each worker at startup, before it ever touches untrusted bytes.

    Windows: drop the worker's own process integrity to Low, so a compromised
    decoder cannot write to the user's (medium-integrity) files or inject into
    other processes. Low integrity keeps read/execute, so importing the venv
    still works. POSIX: cap the worker's address space.
    """
    if sys.platform == "win32":
        if low_il:
            try:
                drop_integrity_low()
            except Exception:
                pass  # best-effort; the Job object still confines the worker
        return
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    except Exception:
        pass


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _JobObjectBasicUIRestrictions = 4
    _JobObjectExtendedLimitInformation = 9

    _LIMIT_ACTIVE_PROCESS = 0x00000008
    _LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
    _LIMIT_JOB_MEMORY = 0x00000200
    _LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    _UILIMIT_ALL = 0x000000FF  # handles|readclip|writeclip|sysparams|display|atoms|desktop|exit

    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _EXT_LIMIT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC_LIMIT),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _UI_RESTRICTIONS(ctypes.Structure):
        _fields_ = [("UIRestrictionsClass", wintypes.DWORD)]

    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    class WindowsJob:
        """A Job object that confines and cleans up the decode workers."""

        def __init__(self, mem_bytes, max_procs):
            self.handle = _k32.CreateJobObjectW(None, None)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            ext = _EXT_LIMIT()
            ext.BasicLimitInformation.LimitFlags = (
                _LIMIT_ACTIVE_PROCESS | _LIMIT_JOB_MEMORY
                | _LIMIT_DIE_ON_UNHANDLED_EXCEPTION | _LIMIT_KILL_ON_JOB_CLOSE)
            ext.BasicLimitInformation.ActiveProcessLimit = int(max_procs)
            ext.JobMemoryLimit = int(mem_bytes)
            if not _k32.SetInformationJobObject(
                    self.handle, _JobObjectExtendedLimitInformation,
                    ctypes.byref(ext), ctypes.sizeof(ext)):
                raise ctypes.WinError(ctypes.get_last_error())
            ui = _UI_RESTRICTIONS(UIRestrictionsClass=_UILIMIT_ALL)
            _k32.SetInformationJobObject(
                self.handle, _JobObjectBasicUIRestrictions,
                ctypes.byref(ui), ctypes.sizeof(ui))

        def assign(self, pid):
            h = _k32.OpenProcess(_PROCESS_TERMINATE | _PROCESS_SET_QUOTA, False, int(pid))
            if not h:
                return False
            try:
                return bool(_k32.AssignProcessToJobObject(self.handle, h))
            finally:
                _k32.CloseHandle(h)

        def close(self):
            if self.handle:
                _k32.CloseHandle(self.handle)  # KILL_ON_JOB_CLOSE -> workers die
                self.handle = None

    # ---- Low-integrity self-drop (privilege drop for a worker) -------------
    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _TokenIntegrityLevel = 25
    _SE_GROUP_INTEGRITY = 0x00000020
    _TOKEN_QUERY = 0x0008
    _TOKEN_ADJUST_DEFAULT = 0x0080

    class _SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class _TOKEN_MANDATORY_LABEL(ctypes.Structure):
        _fields_ = [("Label", _SID_AND_ATTRIBUTES)]

    _adv.ConvertStringSidToSidW.restype = wintypes.BOOL
    _adv.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    _adv.OpenProcessToken.restype = wintypes.BOOL
    _adv.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _adv.SetTokenInformation.restype = wintypes.BOOL
    _adv.SetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _adv.GetTokenInformation.restype = wintypes.BOOL
    _adv.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    _adv.GetLengthSid.restype = wintypes.DWORD
    _adv.GetLengthSid.argtypes = [ctypes.c_void_p]
    _adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    _adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    _adv.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    _adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    _k32.GetCurrentProcess.restype = wintypes.HANDLE
    _k32.LocalFree.argtypes = [wintypes.HANDLE]

    def drop_integrity_low():
        """Lower THIS process's token integrity to Low (S-1-16-4096)."""
        sid = ctypes.c_void_p()
        if not _adv.ConvertStringSidToSidW("S-1-16-4096", ctypes.byref(sid)):
            raise ctypes.WinError(ctypes.get_last_error())
        tok = wintypes.HANDLE()
        try:
            if not _adv.OpenProcessToken(
                    _k32.GetCurrentProcess(),
                    _TOKEN_ADJUST_DEFAULT | _TOKEN_QUERY, ctypes.byref(tok)):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                label = _TOKEN_MANDATORY_LABEL()
                label.Label.Sid = sid
                label.Label.Attributes = _SE_GROUP_INTEGRITY
                size = ctypes.sizeof(label) + _adv.GetLengthSid(sid)
                if not _adv.SetTokenInformation(
                        tok, _TokenIntegrityLevel, ctypes.byref(label), size):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                _k32.CloseHandle(tok)
        finally:
            _k32.LocalFree(sid)

    _IL_NAMES = {0x0000: "untrusted", 0x1000: "low", 0x2000: "medium",
                 0x2100: "medium-plus", 0x3000: "high", 0x4000: "system"}

    def current_integrity():
        """Return this process's integrity level name (e.g. 'low', 'medium')."""
        tok = wintypes.HANDLE()
        if not _adv.OpenProcessToken(_k32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(tok)):
            return "?"
        try:
            need = wintypes.DWORD(0)
            _adv.GetTokenInformation(tok, _TokenIntegrityLevel, None, 0, ctypes.byref(need))
            buf = (ctypes.c_byte * need.value)()
            if not _adv.GetTokenInformation(
                    tok, _TokenIntegrityLevel,
                    ctypes.cast(buf, ctypes.c_void_p), need, ctypes.byref(need)):
                return "?"
            label = ctypes.cast(buf, ctypes.POINTER(_TOKEN_MANDATORY_LABEL)).contents
            cnt = _adv.GetSidSubAuthorityCount(label.Label.Sid)
            rid = _adv.GetSidSubAuthority(label.Label.Sid, cnt[0] - 1)[0]
            return _IL_NAMES.get(rid, f"rid:0x{rid:04x}")
        finally:
            _k32.CloseHandle(tok)

else:  # pragma: no cover - non-Windows fallback
    WindowsJob = None

    def drop_integrity_low():
        pass

    def current_integrity():
        return "n/a"
