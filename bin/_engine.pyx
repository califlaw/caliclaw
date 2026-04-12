# cython: language_level=3
import ctypes
import os
import shutil
import sys


cdef str _decode_backend():
    cdef int k = 0x42
    cdef bytes enc = bytes([0x21, 0x2e, 0x23, 0x37, 0x26, 0x27])
    return bytes(c ^ k for c in enc).decode()


cdef int _check_tracer():
    try:
        with open("/proc/self/status", "rb") as f:
            for line in f:
                if line.startswith(b"TracerPid:"):
                    pid = int(line.split()[1])
                    return pid
    except OSError:
        pass
    return 0


cdef int _check_ld_preload():
    return 1 if os.environ.get("LD_PRELOAD") else 0


cdef int _check_parent():
    try:
        ppid = os.getppid()
        with open(f"/proc/{ppid}/comm", "rb") as f:
            parent_name = f.read().strip().decode()
        bad = [
            bytes([0x71, 0x76, 0x70, 0x63, 0x61, 0x67]),
            bytes([0x6e, 0x76, 0x70, 0x63, 0x61, 0x67]),
            bytes([0x65, 0x66, 0x60]),
            bytes([0x6e, 0x6e, 0x66, 0x60]),
            bytes([0x70, 0x70]),
        ]
        k = 0x02
        bad_names = [bytes(c ^ k for c in b).decode() for b in bad]
        for name in bad_names:
            if name in parent_name:
                return 1
    except OSError:
        pass
    return 0


cdef void _self_ptrace():
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.ptrace(0, 0, 0, 0)
    except (OSError, AttributeError):
        pass


def run() -> int:
    if _check_tracer() != 0:
        return 1
    if _check_ld_preload():
        return 1
    if _check_parent():
        return 1

    backend = os.environ.get("CALICLAW_BACKEND") or _decode_backend()
    binary = shutil.which(backend)
    if not binary:
        print("Error: caliclaw engine not found. Run: caliclaw doctor", file=sys.stderr)
        return 127
    os.execv(binary, ["caliclaw-engine"] + sys.argv[1:])
    return 0
