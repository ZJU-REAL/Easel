"""OS resource ceilings for collector workers. These are not a filesystem sandbox."""
from __future__ import annotations

import os
import math
import subprocess
import sys
import time
from pathlib import Path

from easel.timeouts import TIMEOUT_TREND_CPU, TIMEOUT_TREND_STARTUP
from .protocol import CollectorError


class ProcessLimits:
    def __init__(self, memory_mb: int, seconds: float):
        self.memory = memory_mb * 1024 * 1024
        self.seconds = seconds
        self.handle = None
        self.last_check = 0.0

    def attach(self, process):
        if os.name != "nt":
            return
        import ctypes as c
        from ctypes import wintypes as w

        class Basic(c.Structure):
            _fields_ = [("ProcessTime", c.c_longlong), ("JobTime", c.c_longlong), ("Flags", w.DWORD),
                        ("MinWorkingSet", c.c_size_t), ("MaxWorkingSet", c.c_size_t),
                        ("ActiveProcesses", w.DWORD), ("Affinity", c.c_size_t),
                        ("Priority", w.DWORD), ("Scheduling", w.DWORD)]
        class IO(c.Structure):
            _fields_ = [(name, c.c_ulonglong) for name in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]
        class Extended(c.Structure):
            _fields_ = [("Basic", Basic), ("IO", IO), ("ProcessMemory", c.c_size_t),
                        ("JobMemory", c.c_size_t), ("PeakProcess", c.c_size_t), ("PeakJob", c.c_size_t)]
        class ThreadEntry(c.Structure):
            _fields_ = [("dwSize", w.DWORD), ("usage", w.DWORD), ("tid", w.DWORD),
                        ("pid", w.DWORD), ("priority", w.LONG), ("delta", w.LONG), ("flags", w.DWORD)]
        kernel = c.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([c.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "CreateToolhelp32Snapshot": ([w.DWORD, w.DWORD], w.HANDLE),
            "Thread32First": ([w.HANDLE, c.POINTER(ThreadEntry)], w.BOOL),
            "Thread32Next": ([w.HANDLE, c.POINTER(ThreadEntry)], w.BOOL),
            "OpenThread": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "ResumeThread": ([w.HANDLE], w.DWORD),
        }
        for name, (args, result) in signatures.items():
            function = getattr(kernel, name)
            function.argtypes, function.restype = args, result
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("cannot create collector job")
        info = Extended()
        # Job-wide memory, active child count, CPU time, and kill every child on close.
        info.Basic.Flags = 0x200 | 0x8 | 0x4 | 0x2000
        info.Basic.ActiveProcesses = 8
        info.Basic.JobTime = int(min(TIMEOUT_TREND_CPU, self.seconds + TIMEOUT_TREND_STARTUP) * 10_000_000)
        info.JobMemory = self.memory
        if (not kernel.SetInformationJobObject(self.handle, 9, c.byref(info), c.sizeof(info))
                or not kernel.AssignProcessToJobObject(self.handle, w.HANDLE(int(process._handle)))):
            raise OSError("cannot restrict collector job")
        # Popen created the worker suspended: bind all resource ceilings before any Python executes.
        snapshot = kernel.CreateToolhelp32Snapshot(0x4, 0)
        if snapshot == c.c_void_p(-1).value:
            raise OSError("cannot enumerate worker thread")
        entry = ThreadEntry()
        entry.dwSize = c.sizeof(entry)
        resumed = False
        try:
            valid = kernel.Thread32First(snapshot, c.byref(entry))
            while valid:
                if entry.pid == process.pid:
                    thread = kernel.OpenThread(0x2, False, entry.tid)
                    if thread:
                        try:
                            resumed = kernel.ResumeThread(thread) != 0xFFFFFFFF
                        finally:
                            kernel.CloseHandle(thread)
                    break
                valid = kernel.Thread32Next(snapshot, c.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
        if not resumed:
            raise OSError("cannot resume restricted worker")

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def check(self, process):
        if os.name == "nt" or time.monotonic() - self.last_check < 0.2:
            return
        self.last_check = time.monotonic()
        try:
            group = process.pid
            count, rss = 0, 0
            if sys.platform.startswith("linux"):
                page_size = os.sysconf("SC_PAGE_SIZE")
                for path in Path("/proc").iterdir():
                    if not path.name.isdigit():
                        continue
                    try:
                        with (path / "stat").open("rb") as file:
                            fields = file.read(4096).rsplit(b") ", 1)[1].split()
                        if int(fields[2]) == group:
                            count += 1
                            rss += int(fields[21]) * page_size
                    except (OSError, ValueError, IndexError):
                        continue  # A process may disappear between enumeration and read.
            else:
                # macOS has no /proc and does not reliably support RLIMIT_AS.
                result = subprocess.run(["/bin/ps", "-axo", "pgid=,rss="], capture_output=True,
                                        text=True, check=True, timeout=TIMEOUT_TREND_STARTUP,
                                        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
                for line in result.stdout.splitlines():
                    fields = line.split()
                    try:
                        if len(fields) == 2 and int(fields[0]) == group:
                            count += 1
                            rss += int(fields[1]) * 1024
                    except ValueError:
                        continue
            if count > 8 or rss > self.memory:
                raise CollectorError("resource_limit")
        except (OSError, ValueError, subprocess.SubprocessError):
            raise CollectorError("isolation_failed") from None


def restrict_current_process(memory_mb: int, seconds: float):
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
        return  # The parent assigned the suspended worker to a resource-limited Job Object.
    import resource
    memory = memory_mb * 1024 * 1024
    def limit(kind, value):
        _, inherited_hard = resource.getrlimit(kind)
        cap = value if inherited_hard == resource.RLIM_INFINITY else min(value, inherited_hard)
        resource.setrlimit(kind, (cap, cap))
    try:
        if sys.platform != "darwin":
            limit(resource.RLIMIT_AS, memory)
        cpu = max(1, math.ceil(min(TIMEOUT_TREND_CPU, seconds + TIMEOUT_TREND_STARTUP)))
        limit(resource.RLIMIT_CPU, cpu)
        limit(resource.RLIMIT_CORE, 0)
        limit(resource.RLIMIT_FSIZE, 2 * 1024 * 1024)
    except (OSError, ValueError):
        raise CollectorError("isolation_failed") from None
