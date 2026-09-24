"""Bounded, cancellable device CLI calls; no shell and no system configuration writes."""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


class DeviceError(ValueError):
    """Actionable device or document error safe to expose in the block log."""


class Cancelled(Exception):
    """The owning run has stopped."""


def check_cancel(context=None):
    """Support both regular execution and the public persistent-listener context."""
    if context is None:
        return
    callback = context.services.get("cancel_requested")
    if callable(callback) and callback():
        raise Cancelled()


def run_tool(args, *, timeout=10, context=None, directory=None, budget=1024 * 1024, output=None):
    """Capture bounded diagnostics and terminate the entire child group on Stop/timeout.

    The tiny exec guard arms Linux parent-death handling outside threaded preexec_fn.
    The command never inherits a terminal or the application's standard input.
    """
    check_cancel(context)
    binary = shutil.which(args[0])
    if not binary:
        raise DeviceError(f"Missing {args[0]}. Install the operating system device tools on the BloxSmith host.")
    if not sys.platform.startswith("linux"):
        raise DeviceError("This block currently requires Linux with CUPS / SANE.")
    command = [sys.executable, "-I", str(Path(__file__).with_name("exec_guard.py")), str(os.getpid()), binary, *map(str, args[1:])]
    environment = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        target = output or stdout
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=target, stderr=stderr,
                                   env=environment, start_new_session=True)
        deadline = time.monotonic() + timeout
        try:
            while True:
                check_cancel(context)
                if time.monotonic() > deadline:
                    raise DeviceError(f"{args[0]} timed out. No automatic retry was made; check the device before retrying.")
                if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > 1024 * 1024:
                    raise DeviceError("Device diagnostics exceeded the safety limit.")
                if directory and sum(p.stat().st_size for p in Path(directory).iterdir() if p.is_file()) > budget:
                    raise DeviceError("Scan exceeded its temporary storage limit.")
                if process.poll() is not None:
                    break
                time.sleep(.05)
            stdout.seek(0)
            stderr.seek(0)
            return process.returncode, stdout.read(1024 * 1024).decode("utf-8", "replace"), stderr.read(1024 * 1024).decode("utf-8", "replace")
        finally:
            # Also reap backend descendants after a nominal CLI exit.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)


def require_success(result, tool):
    """Keep diagnostics short, without copying document contents into logs."""
    code, output, error = result
    if code:
        detail = " ".join(error.split())[:400]
        raise DeviceError(f"{tool} failed (exit {code}). {detail or 'Check the installed device and its permissions.'}")
    return output
