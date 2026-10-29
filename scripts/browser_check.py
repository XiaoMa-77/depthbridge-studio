"""End-to-end checks against a running local server; artifacts contain synthetic data."""

import argparse
import json
from pathlib import Path

import numpy as np
from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", default="qa-output")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    checks = []
    with sync_playwright() as playwright:
        edge = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
        browser = playwright.chromium.launch(headless=True, **({"channel": "msedge"} if edge.exists() else {}))
        page = browser.new_page(viewport={"width": 1600, "height": 1050}, device_scale_factor=1)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url)
        page.wait_for_load_state("networkidle")
        page.evaluate('document.fonts.ready')
        assert page.evaluate("document.fonts.check('14px DBSans') && document.fonts.check('28px DBMono')")
        assert page.locator('#page-title').evaluate('e=>parseFloat(getComputedStyle(e).fontSize)') >= 44
        expect(page.locator('.nav')).to_have_count(3)
        expect(page.locator('#image-empty')).to_be_visible()
        expect(page.locator('#metric-resolution')).to_have_text('—')
        expect(page.locator('#capture-frame')).to_be_disabled()
        expect(page.locator('#load-demo')).not_to_be_visible()
        page.locator('.sidebar-tools [data-open="data-dialog"]').click()
        page.locator('#load-demo').click()
        expect(page.locator("#metric-resolution")).to_have_text("640 × 480")
        expect(page.locator("#source-banner")).to_contain_text("SYNTHETIC")
        page.locator(".sampling-settings summary").click()
        page.locator("#sample-radius").select_option("0")
        page.locator(".sampling-settings summary").click()

        def select(u, v):
            page.locator('[data-tab="workbench"]').click()
            bounds = page.locator("#image-canvas").bounding_box()
            assert bounds
            assert abs(bounds["width"] / bounds["height"] - 4 / 3) < 0.02, "Canvas aspect ratio must preserve pixel mapping"
            with page.expect_response(lambda response: response.url.endswith("/api/selections") and response.request.method == "POST") as response:
                page.locator("#image-canvas").click(position={"x": (u + 0.5) / 640 * bounds["width"], "y": (v + 0.5) / 480 * bounds["height"]})
            assert response.value.status == 201, response.value.text()
            sample = response.value.json()["selection"]
            # At scaled-down display sizes, one screen pixel spans several source pixels.
            tolerance = int(np.ceil(640 / bounds["width"]))
            assert max(abs(sample["pixel"][0]-u), abs(sample["pixel"][1]-v)) <= tolerance, (sample["pixel"], [u, v], bounds)
            return sample

        sample = select(200, 200)
        expect(page.locator("#camera-z")).to_have_text("650.00")
        for mode in ("depth", "overlay", "color"):
            page.locator(f'[data-image="{mode}"]').click()
        page.locator("#cloud-coordinates").select_option("base")
        page.locator("#reset-view").click()
        cold_cloud = page.locator('#cloud-canvas').evaluate('c=>c.toDataURL()')
        page.locator('#cloud-palette').select_option('rgb')
        assert page.locator('#cloud-canvas').evaluate('c=>c.toDataURL()') != cold_cloud
        page.locator('#cloud-palette').select_option('ice')
        page.locator('#base-details').evaluate('e=>e.open=false')
        page.locator('#toast').evaluate('e=>e.className=""')
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(output / "workbench.png"), full_page=True)
        checks.append("RGB/depth/overlay, exact pixel selection, linked base cloud")

        truth = np.asarray(page.request.get(args.url + "/api/status").json()["session"]["extrinsic"])
        for index, pixel in enumerate([(180, 180), (240, 180), (180, 240), (240, 240), (360, 360), (430, 230)]):
            sample = select(*pixel)
            base = truth[:3, :3] @ sample["camera_m"] + truth[:3, 3]
            validation = index == 5
            if validation:
                base = base + [0.003, 0, 0]
            page.locator("#use-for-calibration").click()
            for axis, value in zip("xyz", base * 1000, strict=True):
                page.locator(f"#measured-{axis}").fill(str(value))
            page.locator("#pair-label").fill(f"P{index + 1:02}")
            page.locator("#pair-role").select_option("validation" if validation else "calibration")
            with page.expect_response(lambda response: response.url.endswith("/api/pairs") and response.request.method == "POST") as response:
                page.get_by_role("button", name="添加对应点", exact=True).click()
            assert response.value.status == 201
        page.locator("#solve-points").click()
        expect(page.locator("#fit-rms")).to_contain_text("0.000")
        expect(page.locator('#toast')).to_contain_text('标定求解完成')
        page.locator('#toast').evaluate('e=>e.className=""')
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(output / "calibration.png"), full_page=True)
        page.locator('[data-tab="validation"]').click()
        expect(page.locator("#validation-count")).to_have_text("1")
        expect(page.locator("#validation-rms")).to_have_text("3.000")
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(output / "validation.png"), full_page=True)
        checks.append("5-point fit and held-out validation show independent 3 mm error")

        with page.expect_download() as result:
            page.get_by_role("link", name="导出验证数据 ↗", exact=True).click()
        assert result.value.suggested_filename == "depthbridge-measurements.csv"
        result.value.save_as(output / "measurements.csv")
        checks.append("CSV download")

        for width, height in [(1280, 900), (900, 900), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            select(200, 200)
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 2, f"Horizontal overflow at {width}: {overflow}"
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(output / f"responsive-{width}.png"), full_page=True)
        checks.append("1280px, 900px and 390px responsive layout and pixel coordinates")

        page.set_viewport_size({"width": 1600, "height": 1050})
        latest_frame = page.request.get(args.url + "/api/status").json()["frame_id"]
        archive = page.request.get(args.url + f"/api/frames/{latest_frame}/archive")
        assert archive.status == 200
        with page.expect_response(lambda response: response.url.endswith("/api/frames/import")) as response:
            page.locator("#frame-file").set_input_files({"name": "demo.zip", "mimeType": "application/zip", "buffer": archive.body()})
        assert response.value.status == 201
        expect(page.locator("#source-name")).to_have_text("RGB-D 文件回放")
        expect(page.locator("#metric-transform")).to_have_text("尚未标定")
        page.locator('.sidebar-tools [data-open="data-dialog"]').click()
        page.locator("#load-demo").click()
        expect(page.locator("#source-name")).to_have_text("示例模式")
        checks.append("RGB-D import isolation and source switching")
        page.locator('.sidebar-tools [data-open="help-dialog"]').click()
        expect(page.get_by_role("heading", name="从连接到验证")).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.locator('#help-dialog')).not_to_be_visible()
        checks.append("Three-step navigation, explicit examples and contextual help")

        page.locator('.sidebar-tools [data-open="appearance-dialog"]').click()
        page.locator('#motion-enabled').uncheck()
        assert page.evaluate('document.documentElement.dataset.motion') == 'off'
        expect(page.locator('#particles-enabled')).to_be_disabled()
        page.keyboard.press('Escape')
        page.on('dialog', lambda dialog: dialog.accept())
        page.reload()
        page.wait_for_load_state('networkidle')
        assert page.evaluate('document.documentElement.dataset.motion') == 'off'
        page.locator('.sidebar-tools [data-open="appearance-dialog"]').click()
        page.locator('#motion-enabled').check()
        page.locator('#particles-enabled').uncheck()
        assert page.evaluate('document.documentElement.dataset.particles') == 'off'
        page.locator('#particles-enabled').check()
        assert page.evaluate('document.documentElement.dataset.particles') == 'on'
        page.keyboard.press('Escape')
        particle_frame = page.locator('#ambient-particles').evaluate('c=>c.toDataURL()')
        page.wait_for_function("old=>document.getElementById('ambient-particles').toDataURL()!==old", arg=particle_frame)
        assert page.locator('#ambient-particles').evaluate('c=>getComputedStyle(c).pointerEvents') == 'none'
        select(200, 200)
        page.context.grant_permissions(['clipboard-read','clipboard-write'])
        page.locator('#copy-coordinates').click()
        assert 'mm' in page.evaluate('navigator.clipboard.readText()')
        checks.append('Animated particle canvas, motion controls, persisted preference, offline fonts and coordinate copying')

        reduced_context = browser.new_context(reduced_motion='reduce', viewport={'width':1280,'height':900})
        reduced_page = reduced_context.new_page()
        reduced_page.goto(args.url)
        reduced_page.wait_for_load_state('networkidle')
        assert reduced_page.evaluate('document.documentElement.dataset.motion') == 'off'
        assert reduced_page.evaluate('document.documentElement.dataset.particles') == 'off'
        reduced_context.close()
        checks.append('System reduced-motion preference respected')
        page.on("dialog", lambda dialog: dialog.accept())
        browser.close()
    assert not errors, errors
    summary = {"checks": checks, "page_errors": errors, "result": "passed"}
    (output / "browser-report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
