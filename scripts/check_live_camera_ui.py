"""Check a running actual-camera UI without changing its source or calibration."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", type=Path, default=Path("data/live-camera-ui"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as playwright:
        edge = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
        browser = playwright.chromium.launch(headless=True, **({"channel": "msedge"} if edge.exists() else {}))
        page = browser.new_page(viewport={"width": 1600, "height": 1050}, device_scale_factor=1)
        page.on("pageerror", lambda error: errors.append(str(error)))
        initial = page.request.get(args.url + "/api/status").json()
        assert initial["source"] == "realsense", "Connect the real camera first"
        page.goto(args.url)
        page.wait_for_load_state("networkidle")
        expect(page.locator("#source-name")).to_contain_text("D435")
        expect(page.locator("#source-banner")).to_contain_text("LIVE CAMERA")
        expect(page.locator("#metric-transform")).to_have_text("尚未标定")
        before = page.locator("#metric-frame").inner_text()
        page.locator("#live-toggle").click()
        expect(page.locator("#live-toggle")).to_have_text("暂停预览")
        page.wait_for_function("old => document.getElementById('metric-frame').textContent !== old", arg=before)
        second = page.locator("#metric-frame").inner_text()
        page.wait_for_function("old => document.getElementById('metric-frame').textContent !== old", arg=second)
        bounds = page.locator("#image-canvas").bounding_box()
        assert bounds
        with page.expect_response(lambda response: response.url.endswith("/api/selections") and response.request.method == "POST") as response:
            page.locator("#image-canvas").click(position={"x": 190.5/640*bounds["width"], "y": 120.5/480*bounds["height"]})
        assert response.value.status == 201
        selection = response.value.json()["selection"]
        assert selection["source"] == "realsense" and selection["serial"]
        expect(page.locator("#live-toggle")).to_have_text("实时预览")
        expect(page.locator("#camera-z")).to_have_text(f"{selection['depth_m']*1000:.2f}")
        expect(page.locator("#base-z")).to_have_text("—")
        frame_id = int(page.locator("#metric-frame").inner_text().replace("#", "").strip())
        assert selection["frame_id"] == frame_id
        page.screenshot(path=str(args.output / "live-rgb-workbench.png"), full_page=True)
        page.locator('[data-image="depth"]').click()
        expect(page.locator("#image-mode")).to_contain_text("AUTO")
        page.screenshot(path=str(args.output / "live-depth-workbench.png"), full_page=True)
        page.locator('[data-image="overlay"]').click()
        page.screenshot(path=str(args.output / "live-overlay-workbench.png"), full_page=True)
        with page.expect_download() as downloaded:
            page.locator("#download-frame").click()
        downloaded.value.save_as(args.output / "ui-selected-frame.zip")
        assert page.request.get(args.url + "/api/status").json()["source_id"] == initial["source_id"]
        page.on("dialog", lambda dialog: dialog.accept())
        browser.close()
    assert not errors, errors
    report = {"result": "passed", "page_errors": errors, "selection": selection,
              "checks": ["Real D435 live frames", "Pause on click and displayed frame identity", "SDK XYZ values",
                         "No invented base coordinates", "RGB/depth/overlay with adaptive colors", "Actual frame export"]}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
