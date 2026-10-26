"""Actual Qt widgets and native VTK pixels, with generated DICOM only."""

import hashlib
import base64
from io import BytesIO
import json
import time
import zipfile

import numpy as np
from PySide6 import QtCore, QtGui, QtTest
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
    from .received import receive
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
    # The auto-download driver reads the real DOM, using a fixture URL and a
    # recorded browser-download call. No real portal navigation/credential read.
    from unittest.mock import patch
    portal.show()
    process_for(200)
    populated = []
    portal.page.runJavaScript("document.body.innerHTML="+json.dumps(
        '<input type="password" value="fixture-never-read">'
        '<a href="/report.pdf">Report</a><a href="/volume.zip">Scan</a>'
        '<a hidden href="/private.pdf">Hidden</a><a href="https://other.example/a.pdf">Other center</a>'),
        lambda value: populated.append(True))
    assert wait_until(lambda: bool(populated), 10000)
    with patch.object(portal.page, "url", return_value=QtCore.QUrl("https://synthetic-center.example/Patient")), \
         patch.object(portal.page, "download") as browser_download:
        portal.inspect_downloads()
        assert wait_until(lambda: browser_download.called, 10000)
        assert browser_download.call_args.args[0].toString() == "https://synthetic-center.example/volume.zip"
        assert len(portal.attempted_urls) == 1
    portal.close()

    # A second actual browser download is an image, not DICOM. It must be kept,
    # previewed and must clear the previously displayed scan.
    image = QtGui.QImage(64, 48, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor("#27aa88"))
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    encoded_png = base64.b64encode(bytes(buffer.data())).decode("ascii")
    portal.show()
    process_for(200)
    populated = []
    portal.page.runJavaScript("document.body.innerHTML="+json.dumps(
        '<a id="image" download="misleading.dcm" href="data:image/png;base64,'+encoded_png+'">Download report image</a>'),
        lambda value: populated.append(True))
    assert wait_until(lambda: bool(populated), 10000)
    portal.page.runJavaScript("document.getElementById('image').click()")
    assert wait_until(lambda: not window.jobs and bool(window.received_artifacts) and
                      window.received_artifacts[-1].inventory.kind == "png", 20000)
    assert window.loaded is None and window.view.loaded is None
    assert window.document_preview is not None and window.document_preview.isVisible()
    assert all(not path.exists() for path in temp_paths)
    window.document_preview.close()
    # A center's viewer EXE must explain why there is no image and how to recover.
    window.import_received(lambda cancel: receive(b"MZsynthetic-viewer-only", cancel=cancel))
    assert wait_until(lambda: not window.jobs and window.import_notice.isVisible(), 10000)
    assert window.loaded is None and window.view.loaded is None
    assert "فایل اجرایی مرکز" in window.import_notice_title.text()
    assert window.received_artifacts[-1].processing_code == "executable_requires_image_export"
    window.grab().save(str(output/"viewer-exe-guidance.png"))
    # A ZIP-based self-extracting package uses exactly the existing DICOM gate.
    wrapped = b"MZsynthetic-non-runnable-wrapper\x00" + archive.getvalue()
    window.import_received(lambda cancel: receive(wrapped, cancel=cancel))
    assert wait_until(lambda: window.loaded is not None and not window.jobs, 40000)
    assert window.received_artifacts[-1].inventory.kind == "executable_zip"
    assert not window.import_notice.isVisible()
    # A later viewer-only download clears old images, but the earlier scan is
    # explicitly reopenable without inventing a new patient association.
    window.import_received(lambda cancel: receive(b"MZanother-synthetic-viewer", cancel=cancel))
    assert wait_until(lambda: not window.jobs and window.import_notice.isVisible(), 10000)
    with patch("PySide6.QtWidgets.QInputDialog.getItem", return_value=(
            f"{len(window.received_artifacts)-1} · executable_zip · {len(wrapped)} bytes", True)):
        before_count = len(window.received_artifacts)
        window.reopen_received()
        assert wait_until(lambda: window.loaded is not None and not window.jobs, 40000)
        assert len(window.received_artifacts) == before_count
    portal.close()

    # Render a generated PDF in the actual Qt PDF widget, without OCR/model claims.
    pdf = QtCore.QBuffer()
    pdf.open(QtCore.QIODevice.ReadWrite)
    writer = QtGui.QPdfWriter(pdf)
    painter = QtGui.QPainter(writer)
    painter.drawText(100, 100, "Synthetic report - no patient data")
    painter.end()
    del writer
    window.clear()
    window.received_ready(receive(bytes(pdf.data())))
    from PySide6.QtPdf import QPdfDocument
    assert wait_until(lambda: window.document_preview.document.status() == QPdfDocument.Status.Ready, 10000)
    assert window.document_preview.document.pageCount() == 1
    window.document_preview.close()
    report = {"actual_qt_vtk": True, "synthetic_only": True, "rendered_volume_pixels": True,
              "orbit_checked": True, "slice_cine_checked": True, "source_mpr_value_checked": True,
              "lps_linked_point_checked": True, "clip_pixels_checked": True,
              "false_color_pixels_checked": True, "source_voxels_unchanged": True,
              "failed_import_clears_old_images": True, "credentials_cleared": True}
    report.update(private_portal_browser_checked=True, browser_download_to_volume_checked=True,
                  temporary_portal_file_removed=True, explicit_download_automation_checked=True,
                  browser_png_download_and_preview_checked=True, actual_qt_pdf_preview_checked=True)
    report.update(viewer_exe_guidance_checked=True, executable_zip_to_volume_checked=True,
                  earlier_download_can_be_reopened=True)
    (output/"ui-verification.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
