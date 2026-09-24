#!/usr/bin/env python3
"""FB1/FB2/FB3: document contracts, CUPS safety and real installed-package execution."""

import json
from pathlib import Path
import sys
import threading
from types import MappingProxyType

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from blocs.printer.block import PrinterBlock
from blocs.printer.runtime import normalize_config
from blocs.printer.device_process import DeviceError
from device_fixtures import equipment, calls, context, node
from block_test_packages import install_test_package
from ui_smoke_common import (isolated_server, graph_payload, text_node, display_node, data_edge,
    create_project_api, create_run_api, wait_for_run_predicate, stop_run_api)


def test_documents():
    """FB1/FB2: file/text/JSON variants, safe arguments and explicit receipts."""
    block = PrinterBlock()
    assert block.model["version"] == "0.1.0"
    normalize_config(MappingProxyType({"copies": 2, "execution": {"inhibited": False}}))
    for bad in ({"copies": True}, {"copies": 0}, {"printer": "bad;name"}, {"color": "blue"}, {"page_ranges": "4-2"}, {"page_ranges": "1,0"}, {"timeout_sec": 999}):
        try:
            normalize_config(bad)
        except DeviceError:
            pass
        else:
            raise AssertionError(bad)
    with equipment() as root:
        probe = context(root, "printer")
        block.prepare_runtime(probe)
        assert not calls(root), "Preparation contacted equipment"
        assert block.handle_ui_request(node=node("printer"), route="devices", method="POST", values={})["devices"][0]["id"] == "Test_Printer"
        file = root / "document with spaces.pdf"
        file.write_bytes(b"%PDF-1.4\nFixture PDF")
        for value, kind in ((str(file), "file/path"), ("Plain text café", "text/plain"), (json.dumps({"path": str(file)}), "application/json"), (json.dumps({"text": "not-a-path.pdf"}), "application/json")):
            result = block.execute_runtime(context(root, "printer", value=value, content_type=kind,
                config={"copies": 2, "color": "monochrome", "sides": "two-sided-long-edge", "paper": "A4", "page_ranges": "1-3,5"}))
            assert result.status == "success", result.error
            assert json.loads(result.outputs[0].value)["status"] == "submitted"
            call = [item for item in calls(root) if item["tool"] == "lp"][-1]
            assert "print-color-mode=monochrome" in call["args"] and "sides=two-sided-long-edge" in call["args"]
            assert not Path(call["args"][-1]).exists(), "Snapshot was not removed"
        printed = len([item for item in calls(root) if item["tool"] == "lp"])
        for value, kind in ((str(root / "absent.pdf"), "file/path"), ("", "text/plain"), ('{"url":"https://invalid.example/file"}', "application/json"), (str(root), "file/path")):
            result = block.execute_runtime(context(root, "printer", value=value, content_type=kind))
            assert result.status == "failed" and not result.outputs
        assert len([item for item in calls(root) if item["tool"] == "lp"]) == printed
        oversized = root / "large.txt"
        oversized.write_bytes(b"x" * (1024 * 1024 + 1))
        assert block.execute_runtime(context(root, "printer", value=str(oversized), content_type="file/path", config={"max_file_mb": 1})).status == "failed"
        for mode in ("failure", "unknown-job", "no-default"):
            (root / "mode").write_text(mode)
            result = block.execute_runtime(context(root, "printer"))
            assert result.status == "failed" and not result.outputs
        (root / "mode").write_text("slow")
        timed_out = block.execute_runtime(context(root, "printer", config={"timeout_sec": 1}))
        assert timed_out.status == "failed" and "timed out" in timed_out.error
        stop = threading.Event()
        timer = threading.Timer(.3, stop.set)
        timer.start()
        try:
            result = block.execute_runtime(context(root, "printer", services={"cancel_requested": stop.is_set}))
            assert result.status == "cancelled" and not result.outputs
        finally:
            timer.cancel()


def test_installed():
    """FB3: current managed/linked packages, both engines and downstream JSON."""
    for origin in ("managed", "linked"):
        with equipment() as root, isolated_server() as server:
            install_test_package(server, "printer", origin=origin)
            for mode in ("centralized", "zeromq_active"):
                document = graph_payload("Printer test", [text_node("seed", "Document", "Hello printer", 0, 140), node("printer"), display_node("sink", "Receipt", 660, 140)],
                    [data_edge("in", "seed", 1, "printer-test", 1), data_edge("out", "printer-test", 1, "sink", 1)])
                project = create_project_api(server, document=document)["project"]
                before = len([x for x in calls(root) if x["tool"] == "lp"])
                created = create_run_api(server, document, project_id=project["project_id"], runtime_mode=mode)
                try:
                    run = wait_for_run_predicate(server, created["run_id"], lambda r: r.get("node_statuses", {}).get("sink") == "success" or r.get("status") == "failed", "Print receipt did not reach sink", timeout_sec=20)
                    assert run.get("node_statuses", {}).get("sink") == "success", run.get("logs")
                    assert "Test_Printer-42" in str(run["output_values"])
                    assert len([x for x in calls(root) if x["tool"] == "lp"]) == before + 1
                finally:
                    stop_run_api(server, created["run_id"])
                print(f"[ok] printer {origin} {mode}", flush=True)


if __name__ == "__main__":
    test_documents()
    test_installed()
