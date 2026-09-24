"""Disposable fake equipment; these tests never invoke a real device command."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from bloxsmith_app.block_api import BlockRuntimeContext


@contextmanager
def equipment():
    """Replace every device CLI with a fixture before starting the application."""
    with tempfile.TemporaryDirectory(prefix="devices-test-") as temp:
        root = Path(temp)
        binary = root / "bin"
        binary.mkdir()
        script = Path(__file__).with_name("fake_device.py").read_text(encoding="utf-8")
        for name in ("lp", "lpstat", "scanimage"):
            path = binary / name
            path.write_text(f"#!{sys.executable}\n" + script, encoding="utf-8")
            path.chmod(0o755)
        with patch.dict(os.environ, {"PATH": str(binary) + os.pathsep + os.environ.get("PATH", ""), "DEVICE_FIXTURE_ROOT": str(root)}):
            yield root


def calls(root):
    """Return fake CLI invocations for exact no-duplicate/no-Run-side-effect assertions."""
    path = root / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def context(root, kind, *, config=None, value="Test document", content_type="text/plain", services=None):
    """Use only public runtime types and portable temporary paths."""
    block_dir = root / (kind + "-storage")
    return BlockRuntimeContext(run_id="device-test-run", node_id=kind + "-test", kind=kind, root_dir=root,
        config=config or {}, inputs={1: value}, input_content_types={1: content_type},
        input_ports=(SimpleNamespace(id=1, name="document"),) if kind == "printer" else (),
        output_ports=(SimpleNamespace(id=1, name="job" if kind == "printer" else "pdf"),),
        services={"get_block_storage_dir": lambda: block_dir, **(services or {})})


def node(kind):
    """Create a version-pinned current-source block node."""
    if kind == "printer":
        from blocs.printer.block import PrinterBlock
        block = PrinterBlock()
    else:
        from blocs.scanner.block import ScannerBlock
        block = ScannerBlock()
    result = block.build_node_payload(node_id=kind + "-test", position={"x": 320, "y": 140})
    result["block_version"] = "0.1.0"
    result["config"].update({"printer": "Test_Printer"} if kind == "printer" else {"device": "test:scanner", "timeout_sec": 10})
    return result
