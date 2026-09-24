#!/usr/bin/env python3
"""FB4/FB3: installed-release forms, real canvas actions, translations and responsive QA."""

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from playwright.sync_api import sync_playwright, expect
from block_test_artifacts import artifact_path
from block_test_packages import install_test_package, surface_payload
from device_fixtures import node, equipment, calls
from ui_smoke_common import (isolated_server, graph_payload, display_node, data_edge, create_project_api,
    project_editor_url, attach_console_guards, assert_no_blocking_console_errors, get_run_api, wait_for_run_predicate)

KIND = "printer"


def main():
    """Exercise unchanged package sources in supervised managed and linked installations."""
    for origin in ("managed", "linked"):
        with equipment() as hardware, isolated_server() as server, sync_playwright() as playwright:
            model = install_test_package(server, KIND, origin=origin)
            candidate = node(KIND)
            for surface in ("modal", "inspector_panel"):
                surface_payload(server, model, candidate, surface=surface)
            document = graph_payload("Device UI", [candidate, display_node("sink", "Result", 650, 140)],
                                     [data_edge("out", KIND + "-test", 1, "sink", 1)])
            project = create_project_api(server, document=document)["project"]
            url = project_editor_url(server.base_url, project["project_id"], workspace_project_id=project["workspace_project_id"])
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.add_init_script("window.localStorage.setItem('bloxsmith.inspectorPinned','true')")
                errors = attach_console_guards(page)
                page.goto(url)
                card = page.locator('.canvas-node[data-node-id="' + KIND + '-test"]')
                expect(card).to_be_visible()
                if KIND == "scanner":
                    expect(card.locator('[data-scan-start]')).to_be_disabled()
                card.locator('h3').dblclick()
                modal = page.locator('.cw-' + KIND + '-modal')
                expect(modal).to_be_visible()
                expect(modal.locator('[data-block-apply]')).to_be_disabled()
                modal.locator('[data-device-refresh]').click()
                expect(modal.locator('[data-device-status]')).to_contain_text("updated")
                expect(modal.locator('[data-device-select]')).to_have_value("test:scanner" if KIND == "scanner" else "Test_Printer")
                expect(modal.locator('[data-block-apply]')).to_be_disabled()
                field = "resolution" if KIND == "scanner" else "copies"
                value = "150" if KIND == "scanner" else "2"
                modal.locator('[data-block-config-field="' + field + '"]').fill(value)
                expect(modal.locator('[data-block-apply]')).to_be_enabled()
                for width, height, label in ((1440, 900, "desktop"), (390, 740, "mobile"), (320, 568, "small")):
                    page.set_viewport_size({"width": width, "height": height})
                    page.wait_for_timeout(120)
                    bounds = modal.evaluate("""(panel) => {
                      const box=panel.getBoundingClientRect(), apply=panel.querySelector('[data-block-apply]').getBoundingClientRect();
                      return { inside: box.left >= -1 && box.right <= innerWidth + 1 && box.bottom <= innerHeight + 1,
                        apply: apply.bottom <= innerHeight && apply.top >= 0,
                        overflow: panel.scrollWidth > panel.clientWidth + 1,
                        background: getComputedStyle(panel).backgroundColor };
                    }""")
                    page.screenshot(path=artifact_path(KIND + "-" + origin + "-" + label + ".png"))
                    assert bounds["inside"] and bounds["apply"] and not bounds["overflow"], bounds
                    assert bounds["background"] not in {"transparent", "rgba(0, 0, 0, 0)"}
                page.set_viewport_size({"width": 1440, "height": 900})
                with page.expect_response(lambda response: response.url.endswith('/ui-action') and response.request.method == 'POST') as applied:
                    modal.locator('[data-block-apply]').click()
                assert not applied.value.json().get("error"), applied.value.json()
                if modal.is_visible():
                    modal.locator('[data-close-block-modal]').first.click()
                page.reload()
                card.locator('h3').dblclick()
                expect(modal.locator('[data-block-config-field="' + field + '"]')).to_have_value(value)
                modal.locator('[data-block-config-field="' + field + '"]').fill("250" if KIND == "scanner" else "3")
                modal.locator('[data-close-block-modal]').first.click()
                card.locator('h3').dblclick()
                expect(modal.locator('[data-block-config-field="' + field + '"]')).to_have_value(value)
                modal.locator('[data-close-block-modal]').first.click()
                card.click(position={"x": 25, "y": 20})
                inspector = page.locator('.cw-device-inspector:visible')
                expect(inspector).to_be_visible()
                expect(inspector.locator('[data-block-config-field="' + field + '"]')).to_have_value(value)
                inspector.locator('[data-block-config-field="color"]').select_option("gray" if KIND == "scanner" else "monochrome")
                with page.expect_response(lambda response: response.url.endswith('/ui-action') and response.request.method == 'POST') as applied_panel:
                    inspector.locator('[data-block-apply]').click()
                assert not applied_panel.value.json().get("error"), applied_panel.value.json()
                page.screenshot(path=artifact_path(KIND + "-" + origin + "-inspector.png"))
                if KIND == "scanner":
                    # Real Run is passive; a real card click publishes one PDF downstream.
                    before = len([item for item in calls(hardware) if any(arg.startswith("--batch=") for arg in item["args"])])
                    page.click("#activeRuntimeModeButton")
                    with page.expect_response(lambda response: response.url.endswith("/runs/prepare") and response.request.method == "POST") as prepared:
                        page.click("#loadRunButton")
                    run_id = prepared.value.json()["run_id"]
                    expect(card.locator('[data-scan-start]')).to_be_enabled(timeout=15000)
                    assert len([item for item in calls(hardware) if any(arg.startswith("--batch=") for arg in item["args"])]) == before
                    page.screenshot(path=artifact_path(KIND + "-" + origin + "-card.png"))
                    card.locator('[data-scan-start]').click()
                    run = wait_for_run_predicate(server, run_id, lambda r: r.get("node_statuses", {}).get("sink") == "success",
                        "Scan button did not publish a PDF", timeout_sec=20)
                    assert ".pdf" in str(run["output_values"])
                    expect(card.locator('[data-scan-start]')).to_be_enabled(timeout=10000)
                    previous = str(run["output_values"]["scanner-test:1"])
                    card.locator('[data-scan-start]').click()
                    wait_for_run_predicate(server, run_id, lambda r: str(r.get("output_values", {}).get("scanner-test:1")) != previous,
                        "Second scan did not produce a fresh PDF", timeout_sec=20)
                    assert len([item for item in calls(hardware) if any(arg.startswith("--batch=") for arg in item["args"])]) == before + 2
                    page.click("#stopRunButton")
                    expect(card.locator('[data-scan-start]')).to_be_disabled()
                # English/French catalogs are package-owned and survive a fresh page.
                page.goto(server.base_url + "/")
                page.locator("#homeApplicationSettingsButton").click()
                page.locator("#applicationLanguageSelect").select_option("fr")
                page.wait_for_function("window.CWMessages.getLanguage() === 'fr'")
                page.goto(url)
                card.locator('h3').dblclick()
                expect(modal.locator('[data-device-refresh]')).to_have_text("Actualiser")
                expect(modal.locator('[data-block-config-field="color"]')).to_have_value("gray" if KIND == "scanner" else "monochrome")
                page.screenshot(path=artifact_path(KIND + "-" + origin + "-french.png"))
                assert page.evaluate("!window.CWBlockUiBlocks?." + KIND)
                assert_no_blocking_console_errors(errors)
            finally:
                browser.close()
        print("[ok] " + KIND + " " + origin + " UI", flush=True)


if __name__ == "__main__":
    main()
