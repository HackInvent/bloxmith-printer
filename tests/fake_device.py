"""Test executable selected solely by the fixture PATH, never by production config."""

import json
import os
from pathlib import Path
import sys
import time

root = Path(os.environ["DEVICE_FIXTURE_ROOT"])
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
mode = (root / "mode").read_text().strip() if (root / "mode").exists() else "ok"
record = {"tool": tool, "args": args}
if tool == "lp":
    record["document"] = Path(args[-1]).read_bytes()[:100].decode("utf-8", "replace")
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps(record) + "\n")
if tool == "lpstat":
    if "-d" in args:
        print("no system default destination" if mode == "no-default" else "system default destination: Test_Printer")
    else:
        print("printer Test_Printer is idle. enabled since today")
    raise SystemExit(0)
if tool == "scanimage" and any(arg.startswith("--formatted-device-list=") for arg in args):
    print("test:scanner\tTest Scanner")
    raise SystemExit(0)
if tool == "scanimage" and "--help" in args:
    print("  --mode " + ("Gray" if mode == "gray-only" else "Color|Gray|Lineart") + " [Color]\n  --source Flatbed|ADF|ADF Duplex [Flatbed]\n  --resolution 75..600dpi [300]\n  -x 0..216mm\n  -y 0..300mm")
    raise SystemExit(0)
if mode == "slow":
    (root / "active.pid").write_text(str(os.getpid()))
    time.sleep(30)
if mode == "failure":
    print("Fixture paper jam", file=sys.stderr)
    raise SystemExit(9)
if tool == "lp":
    print("unexpected status" if mode == "unknown-job" else "request id is Test_Printer-42 (1 file(s))")
    raise SystemExit(0)
if tool == "scanimage":
    if mode == "empty":
        raise SystemExit(7)
    template = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--batch="))
    count = int(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--batch-count=")))
    for index in range(1, min(3, count) + 1):
        path = Path(template % index)
        if mode == "invalid-image":
            path.write_bytes(b"not an image")
        elif mode == "huge-image":
            path.write_bytes(b"P6\n100000 100000\n255\n")
        else:
            path.write_bytes(b"P6\n20 30\n255\n" + bytes((60 * index, 100, 190)) * 600)
    if mode == "partial-jam":
        print("Fixture jam after one page", file=sys.stderr)
        raise SystemExit(9)
    raise SystemExit(7 if count > 3 else 0)
raise SystemExit(99)
