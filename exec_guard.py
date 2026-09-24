"""Exec one owned CLI and ensure it dies if its managed block host disappears."""

import ctypes
import os
import signal
import sys


def main():
    """Arm PR_SET_PDEATHSIG before exec, including the parent-death race check."""
    parent = int(sys.argv[1])
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent:
        return 125
    os.execv(sys.argv[2], sys.argv[2:])
    return 125


if __name__ == "__main__":
    raise SystemExit(main())
