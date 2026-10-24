"""Actual Qt widgets and native VTK pixels, with generated DICOM only."""

import hashlib
import base64
from io import BytesIO
import json
import time
import zipfile

import numpy as np
from PySide6 import QtCore, QtTest
from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
from vtkmodules.vtkIOImage import vtkPNGWriter
from vtkmodules.util.numpy_support import vtk_to_numpy


def wait_until(predicate, timeout_ms):
    # A real Qt event loop releases the GIL so Python QThread workers can run.
    # Repeated QTest.qWait calls can starve those workers on some PySide builds.
    loop = QtCore.QEventLoop()
    poll = QtCore.QTimer()
    poll.setInterval(20)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline = QtCore.QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout_ms)
    loop.exec()
    poll.stop()
    deadline.stop()
    return predicate()


def process_for(milliseconds):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def check_ui(application, window, output):
    output.mkdir(parents=True, exist_ok=True)
    QtTest.QTest.mouseClick(window.demo_button, QtCore.Qt.LeftButton)
    wait_until(lambda: window.loaded is not None or not window.jobs, 60000)
    assert window.loaded is not None, "Synthetic import failed or timed out: "+window.status.text()
    process_for(150)
    loaded = window.loaded
    original = hashlib.sha256(loaded.voxels.tobytes()).hexdigest()

    def capture():
        window.view.render()
        image = vtkWindowToImageFilter()
        image.SetInput(window.view.widget.GetRenderWindow())
        image.ReadFrontBufferOff()
        image.Update()
        pixels = vtk_to_numpy(image.GetOutput().GetPointData().GetScalars())
        return image, pixels.copy()

    image, before = capture()
    assert np.count_nonzero(before[:, :3].max(axis=1) > 80) > 1000, "Real volume pixels must be visible."
    writer = vtkPNGWriter()
    writer.SetInputConnection(image.GetOutputPort())
    writer.SetFileName(str(output/"volume.png"))
    writer.Write()
    position = window.view.renderer.GetActiveCamera().GetPosition()
    QtTest.QTest.mouseClick(window.orbit_button, QtCore.Qt.LeftButton)
    process_for(180)
    QtTest.QTest.mouseClick(window.orbit_button, QtCore.Qt.LeftButton)
    assert position != window.view.renderer.GetActiveCamera().GetPosition()
    window.view.reset()
    window.slices["z"].slider.setValue(20)
    assert window.cursor[2] == 20
    # QImage is built from the source pixels, before its display crosshair.
    gray = window.slices["z"].canvas.image.pixelColor(4, 4).red()
    expected = int(np.round(np.clip((loaded.voxels[20, 4, 4]-window.window_center.value())/window.window_width.value()+.5, 0, 1)*255))
    assert gray == expected
    point = (loaded.affine_lps @ [*window.cursor, 1])[:3]
    np.testing.assert_allclose(window.view.marker.GetPosition(), point)
    old_z = window.cursor[2]
    QtTest.QTest.mouseClick(window.cine_button, QtCore.Qt.LeftButton)
    process_for(320)
    QtTest.QTest.mouseClick(window.cine_button, QtCore.Qt.LeftButton)
    assert old_z != window.cursor[2]
    _, before_clip = capture()
    window.clip.setValue(32)
    window.clip_box.setChecked(True)
    _, after_clip = capture()
    assert not np.array_equal(before_clip, after_clip), "Clipping must alter rendered pixels."
    window.clip_box.setChecked(False)
    _, before_palette = capture()
    window.color_box.setChecked(True)
    _, after_palette = capture()
    assert not np.array_equal(before_palette, after_palette), "False-color selection must alter pixels."
    assert original == hashlib.sha256(loaded.voxels.tobytes()).hexdigest()
    window.grab().save(str(output/"desktop.png"))
    # A failed replacement clears the old patient volume and source slices.
    window.url.setText("https://user:private@invalid.example/study?secret=never-log")
    QtTest.QTest.mouseClick(window.fetch_button, QtCore.Qt.LeftButton)
    assert wait_until(lambda: not window.jobs, 5000)
    assert window.loaded is None and window.view.loaded is None
    assert all(panel.canvas.image is None for panel in window.slices.values())
    assert not window.url.text() and not window.token.text()
    assert "private" not in window.status.text() and "never-log" not in window.status.text()
    # Real private WebEngine page -> browser-generated ZIP download -> volume.
    # No patient or external portal request: the login form and bytes are fixtures.
    from .portal import PortalWindow
    from .volume import demonstration
    catalog = demonstration()
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for i, content in enumerate(catalog.series[0].snapshots):
            bundle.writestr(f"slice-{i}.dcm", content)
    encoded = base64.b64encode(archive.getvalue()).decode("ascii")
    window.portal = portal = PortalWindow(window)
    portal.downloaded.connect(window.portal_download)
    assert portal.profile.isOffTheRecord()
    completed, temp_paths = [], []
    portal.downloaded.connect(lambda path, temp: temp_paths.append(path))
    portal.page.loadFinished.connect(completed.append)
    fixture_html = ('<div style="background:#132332;color:white;font:20px sans-serif">'
                      '<h2>Synthetic center portal</h2><p>Fixture-only code and password</p>'
                      '<input id="code"><input id="password" type="password">'
                      '<button onclick="document.getElementById(\'download\').hidden=false">Login</button>'
                      f'<a id="download" hidden download="synthetic-only.zip" href="data:application/zip;base64,{encoded}">Download DICOM ZIP</a></div>')
    # Keep production navigation policy intact: setHtml internally navigates to
    # data:, which a real portal must not use as a top-level login origin.
    portal.web.setUrl(QtCore.QUrl("about:blank"))
    portal.show()
    wait_until(lambda: bool(completed), 20000)
    assert completed and completed[-1], "Real private browser must load the fixture portal."
    populated = []
    portal.page.runJavaScript("document.body.innerHTML="+json.dumps(fixture_html), lambda value: populated.append(True))
    assert wait_until(lambda: bool(populated), 10000)
    portal.page.runJavaScript("document.getElementById('code').value='fixture';document.getElementById('password').value='fixture';document.querySelector('button').click();document.getElementById('download').click()")
    wait_until(lambda: window.loaded is not None and not window.jobs, 40000)
    assert window.loaded is not None and temp_paths, "Browser ZIP download must reach the actual importer."
    assert all(not path.exists() for path in temp_paths), "Temporary portal downloads must be deleted after snapshot import."
    portal.grab().save(str(output/"portal-fixture.png"))
    portal.close()
    report = {"actual_qt_vtk": True, "synthetic_only": True, "rendered_volume_pixels": True,
              "orbit_checked": True, "slice_cine_checked": True, "source_mpr_value_checked": True,
              "lps_linked_point_checked": True, "clip_pixels_checked": True,
              "false_color_pixels_checked": True, "source_voxels_unchanged": True,
              "failed_import_clears_old_images": True, "credentials_cleared": True}
    report.update(private_portal_browser_checked=True, browser_download_to_volume_checked=True,
                  temporary_portal_file_removed=True)
    (output/"ui-verification.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
