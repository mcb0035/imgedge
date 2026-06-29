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


def worker_init(mem_bytes):
    """Run inside each worker at startup. POSIX: cap address space."""
    if sys.platform == "win32":
        return  # Windows workers are confined from the parent via the Job object
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

else:  # pragma: no cover - non-Windows fallback
    WindowsJob = None
