"""Real Chromium/WebGL check of the offline bundle; no listening socket required.

Playwright serves the exact exported files through route.fulfill. Every external
request is denied. Geometry, image bytes and Three.js remain the real artifacts.
"""

import argparse
import hashlib
import json
import mimetypes
from pathlib import Path
import struct
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def check_viewer(artifact: Path, screenshot: Path, *, chromium: str | None = None):
    artifact = artifact.resolve()
    manifest = json.loads((artifact / "scene.json").read_text())
    nz, ny, nx = manifest["volume"]["shape_zyx"]
    errors, external = [], []
    corrupt_volume = False
    origin = "http://127.0.0.1:18765"
    allowed = {"index.html", "app.js", "style.css", "scene.json", "volume.f32", "labels.u8",
               "vendor/three.module.js", "vendor/three.core.js", "vendor/OrbitControls.js"}
    with sync_playwright() as playwright:
        launch = dict(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage",
                                         "--enable-unsafe-swiftshader", "--use-angle=swiftshader"])
        if chromium:
            launch["executable_path"] = chromium
        browser = playwright.chromium.launch(**launch)
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 1050}, device_scale_factor=1)
            page.on("pageerror", lambda error: errors.append(str(error)))

            def serve(route):
                parts = urlsplit(route.request.url)
                path = parts.path.lstrip("/") or "index.html"
                if parts.scheme != "http" or parts.netloc != "127.0.0.1:18765" or path not in allowed:
                    external.append(route.request.url)
                    return route.abort()
                mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
                if path == "volume.f32" and corrupt_volume:
                    raw = bytearray((artifact/path).read_bytes())
                    raw[0] ^= 1
                    return route.fulfill(body=bytes(raw), content_type=mime)
                return route.fulfill(path=str(artifact / path), content_type=mime)

            page.route("**/*", serve)
            page.goto(origin + "/index.html", wait_until="networkidle")
            page.locator('#workspace[data-ready="true"]').wait_for(timeout=30000)
            assert not page.locator("#error").is_visible(), "Viewer reported an error."
            canvas = page.locator("#knee-3d-canvas")
            page.wait_for_function("Number(document.querySelector('#knee-3d-canvas').dataset.frame)>0")
            pixels = canvas.evaluate("""canvas => {
              const gl = canvas.getContext('webgl2');
              if (!gl) throw Error('Actual WebGL2 is required');
              const data = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
              gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,data);
              let count=0;
              for(let i=0;i<data.length;i+=4) if(data[i+3]>10 && Math.max(data[i],data[i+1],data[i+2])-Math.min(data[i],data[i+1],data[i+2])>20) count++;
              return count;
            }""")
            assert pixels > 1000, "Real colored surface pixels must be rendered."
            assert page.locator("#structure-list input:checked").count() == 8
            assert page.get_by_role("note").inner_text().find("کاملاً ساختگی") >= 0

            def change(action):
                frame = int(canvas.get_attribute("data-frame"))
                before = hashlib.sha256(canvas.screenshot()).hexdigest()
                action()
                page.wait_for_function("old => Number(document.querySelector('#knee-3d-canvas').dataset.frame)>old", arg=frame)
                return before != hashlib.sha256(canvas.screenshot()).hexdigest()

            assert change(lambda: page.locator("#structure-4").uncheck()), "Visibility must affect rendering."
            page.locator("#structure-4").check()
            assert change(lambda: page.locator("#opacity").evaluate("node=>{node.value=100;node.dispatchEvent(new Event('input'))}"))
            assert change(lambda: page.locator("#clip").check()), "Clipping must affect rendering."
            page.locator("#clip").uncheck()
            page.locator("#slice-z").evaluate("node=>{node.value=20;node.dispatchEvent(new Event('input'))}")
            assert page.locator("#value-z").inner_text() == f"21 / {nz}"
            page.locator("#overlay").uncheck()
            rgba = page.locator("#slice-canvas-z").evaluate("c=>Array.from(c.getContext('2d').getImageData(4,4,1,1).data)")
            source = (artifact / "volume.f32").read_bytes()
            value = struct.unpack_from("<f", source, ((20 * ny + 4) * nx + 4)*4)[0]
            center = int(page.locator("#window-center").input_value())
            width = int(page.locator("#window-width").input_value())
            expected = int(255 * min(1, max(0, (value-center)/width+.5)) + .5)
            assert rgba[:3] == [expected]*3, "MPR must use the actual reconstructed voxel value."
            spacing = manifest["volume"]["spacing_xyz_mm"]
            rect = page.locator("#slice-canvas-z").bounding_box()
            assert abs(rect["width"]/rect["height"] - nx*spacing[0]/(ny*spacing[1])) < .02
            old_location = page.locator("#voxel-location").inner_text()
            page.locator("#slice-canvas-z").click(position={"x":20, "y":20})
            assert page.locator("#voxel-location").inner_text() != old_location
            assert change(lambda: page.locator("#inside").click()), "Internal camera must change the view."
            assert page.locator("#inside").get_attribute("aria-pressed") == "true"
            canvas.focus()
            assert change(lambda: page.keyboard.press("w")), "Internal navigation must move the camera."
            page.locator("#overview").click()
            page.locator("#overlay").check()
            page.locator("#slice-z").evaluate(f"node=>{{node.value={nz//2};node.dispatchEvent(new Event('input'))}}")
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot), full_page=True)
            # Verify controls stay usable and overflow is absent on a phone viewport.
            page.set_viewport_size({"width":390, "height":844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth+1")
            page.locator("#inside").click()
            assert page.locator("#inside").get_attribute("aria-pressed") == "true"
            assert not errors, "No browser runtime error is allowed."
            assert not external, "No external network request is allowed."
            corrupt_volume = True
            page.reload(wait_until="networkidle")
            page.locator('#error').wait_for(state="visible")
            assert page.locator('#workspace').get_attribute('data-ready') is None
            return {"synthetic_only":True, "modality":manifest["volume"]["modality"],
                    "actual_webgl2":True, "colored_surface_pixels":pixels,
                    "structures":8, "mpr_voxel_checked":True, "physical_aspect_checked":True,
                    "linked_cursor_checked":True, "clipping_checked":True,
                    "internal_navigation_checked":True, "mobile_layout_checked":True,
                    "corrupt_volume_rejected":True,
                    "external_requests":0, "browser_errors":0}
        except Exception:
            if 'page' in locals():
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot.with_name('failure-'+screenshot.name)), full_page=True)
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--chromium")
    args = parser.parse_args()
    print(json.dumps(check_viewer(args.artifact, args.screenshot, chromium=args.chromium), indent=2, sort_keys=True))
