import os
import sys
from contextlib import contextmanager

from .util import dbg

if sys.platform == 'win32':
    # `msvcrt.locking` doesn't really block and only polls every second, and `filelock`
    # just polls more frequently on every platform. We use `LockFileEx` directly
    # for actual blocking behavior.

    import msvcrt
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32

    # https://docs.microsoft.com/en-us/windows/win32/api/minwinbase/ns-minwinbase-overlapped
    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ('Internal', wintypes.ULONG),
            ('InternalHigh', wintypes.ULONG),
            ('Offset', wintypes.DWORD),
            ('OffsetHigh', wintypes.DWORD),
            ('hEvent', wintypes.HANDLE),
        ]

    # https://docs.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex
    LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
    LOCKFILE_EXCLUSIVE_LOCK = 0x00000002

    # BOOL LockFileEx(HANDLE, DWORD, DWORD, DWORD, DWORD, LPOVERLAPPED)
    LockFileEx = kernel32.LockFileEx
    LockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(OVERLAPPED),
    ]
    LockFileEx.restype = wintypes.BOOL

    # BOOL UnlockFileEx(HANDLE, DWORD, DWORD, DWORD, LPOVERLAPPED)
    UnlockFileEx = kernel32.UnlockFileEx
    UnlockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(OVERLAPPED),
    ]
    UnlockFileEx.restype = wintypes.BOOL

    # https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--0-499-
    ERROR_LOCK_VIOLATION = 0x21

    def _overlapped():
        r = OVERLAPPED()
        r.Offset = 0
        r.OffsetHigh = 0
        return ctypes.byref(r)

    class FileLock:
        def __init__(self, fd):
            self._handle = msvcrt.get_osfhandle(fd)

        def acquire(self, blocking=True):
            flags = LOCKFILE_EXCLUSIVE_LOCK
            if not blocking:
                flags |= LOCKFILE_FAIL_IMMEDIATELY

            if not LockFileEx(self._handle, flags, 0, 1, 0, _overlapped()):
                code = ctypes.GetLastError()
                if not blocking and code == ERROR_LOCK_VIOLATION:
                    raise BlockingIOError
                raise ctypes.WinError(code)

        def release(self):
            if not UnlockFileEx(self._handle, 0, 1, 0, _overlapped()):
                raise ctypes.WinError()

else:
    import fcntl

    class FileLock:
        def __init__(self, fd):
            self._fd = fd

        def acquire(self, blocking=True):
            flags = fcntl.LOCK_EX
            if not blocking:
                flags |= fcntl.LOCK_NB
            fcntl.flock(self._fd, flags)

        def release(self):
            fcntl.flock(self._fd, fcntl.LOCK_UN)


@contextmanager
def wait_lock(file):
    fd = os.open(file, os.O_RDONLY | os.O_CREAT)
    lock = FileLock(fd)

    try:
        lock.acquire(blocking=False)
    except BlockingIOError:
        dbg(file + ': waiting for lock', must=True)
        waited = True
        lock.acquire()
    else:
        waited = False

    try:
        yield waited
    finally:
        # Keep the lock file for next use, so no `unlink` here.
        lock.release()
        os.close(fd)
