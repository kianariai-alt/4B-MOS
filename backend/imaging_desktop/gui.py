"""Native Qt/VTK desktop interface. All imported pixels stay in this process."""

from pathlib import Path
import threading

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.util.numpy_support import numpy_to_vtk
from vtkmodules.vtkCommonDataModel import vtkImageData, vtkPlane
from vtkmodules.vtkCommonMath import vtkMatrix4x4
from vtkmodules.vtkCommonDataModel import vtkPiecewiseFunction
from vtkmodules.vtkFiltersSources import vtkSphereSource
from vtkmodules.vtkRenderingCore import (
    vtkActor, vtkColorTransferFunction, vtkPolyDataMapper, vtkRenderer, vtkVolume, vtkVolumeProperty,
)
from vtkmodules.vtkRenderingVolume import vtkFixedPointVolumeRayCastMapper
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401 -- native rendering factory
import vtkmodules.vtkRenderingVolumeOpenGL2  # noqa: F401

from .sources import ImportFailure, download_bytes, open_local, read_artifact
from .received import receive
from .volume import demonstration, load_series


MESSAGES = {
    "cancelled": "عملیات لغو شد.",
    "https_download_link_required": "لینک مستقیم HTTPS بدون نام کاربری در نشانی وارد کنید.",
    "portal_page_requires_dicom_download": "این نشانی صفحهٔ مشاهده یا ورود است. از مرکز، دانلود DICOM/ZIP بگیرید و فایل یا لینک مستقیم آن را باز کنید.",
    "authentication_required": "مرکز دسترسی را نپذیرفت. لینک معتبر دانلود یا توکن دسترسی لازم است.",
    "cross_host_redirect_blocked": "لینک به میزبان دیگری هدایت شد. لینک نهایی دانلود را از مرکز دریافت کنید.",
    "compressed_dicom_not_supported": "این نسخه DICOM فشرده را باز نمی‌کند؛ خروجی DICOM غیرفشرده از مرکز دریافت کنید.",
    "classic_monochrome_mr_ct_required": "پروفایل فعلی برای CT/MR تک‌فریم خاکستری، حداکثر ۵۱۲ پیکسل در هر بُعد است.",
    "inconsistent_or_nonrectilinear_series": "هندسهٔ سری برای ساخت حجم یکنواخت کافی نیست؛ گزارش فنی را بررسی کنید.",
    "no_dicom_instances": "فایل DICOM تصویری در ورودی پیدا نشد.",
    "duplicate_dicom_instance": "برش DICOM تکراری در ورودی وجود دارد.",
    "voxel_limit": "حجم از سقف این نسخه بیشتر است؛ یک سری کوچک‌تر انتخاب کنید.",
}


class Job(QtCore.QThread):
    ready = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    progress = QtCore.Signal(int, int)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation, self.cancel = operation, threading.Event()

    def run(self):
        try:
            self.ready.emit(self.operation(self.cancel))
        except ImportFailure as error:
            self.failed.emit(str(error))
        except Exception:
            self.failed.emit("processing_failed")
        finally:
            self.operation = None


class SliceCanvas(QtWidgets.QWidget):
    selected = QtCore.Signal(int, int)

    def __init__(self):
        super().__init__()
        self.image, self.target, self.cross, self.ratio = None, QtCore.QRectF(), (0, 0), 1
        self.setMinimumSize(160, 125)
        self.setCursor(QtCore.Qt.CrossCursor)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor("#090f18"))
        if self.image is None:
            return
        width = min(self.width()-8, (self.height()-8)*self.ratio)
        height = width/self.ratio
        self.target = QtCore.QRectF((self.width()-width)/2, (self.height()-height)/2, width, height)
        painter.drawImage(self.target, self.image)
        painter.setPen(QtGui.QPen(QtGui.QColor("#67dac2"), 1))
        u, v = self.cross
        px = self.target.left()+(u+.5)*width/self.image.width()
        py = self.target.top()+(v+.5)*height/self.image.height()
        painter.drawLine(QtCore.QPointF(px, self.target.top()), QtCore.QPointF(px, self.target.bottom()))
        painter.drawLine(QtCore.QPointF(self.target.left(), py), QtCore.QPointF(self.target.right(), py))

    def mousePressEvent(self, event):
        if self.image is not None and self.target.contains(event.position()):
            u = min(self.image.width()-1, int((event.position().x()-self.target.left())/self.target.width()*self.image.width()))
            v = min(self.image.height()-1, int((event.position().y()-self.target.top())/self.target.height()*self.image.height()))
            self.selected.emit(u, v)


class SlicePanel(QtWidgets.QGroupBox):
    changed = QtCore.Signal(int)
    selected = QtCore.Signal(int, int)

    def __init__(self, title):
        super().__init__(title)
        layout = QtWidgets.QVBoxLayout(self)
        self.canvas, self.slider, self.value = SliceCanvas(), QtWidgets.QSlider(QtCore.Qt.Horizontal), QtWidgets.QLabel("—")
        self.slider.valueChanged.connect(self.changed.emit)
        self.canvas.selected.connect(self.selected.emit)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.slider)
        layout.addWidget(self.value)


class VolumeView(QtWidgets.QFrame):
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.widget = QVTKRenderWindowInteractor(self)
        layout.addWidget(self.widget)
        self.renderer = vtkRenderer()
        self.renderer.SetBackground(.035, .06, .095)
        self.widget.GetRenderWindow().AddRenderer(self.renderer)
        self.widget.GetRenderWindow().GetInteractor().SetInteractorStyle(vtkInteractorStyleTrackballCamera())
        self.volume, self.mapper, self.loaded = None, None, None
        self.plane = vtkPlane()

    def clear(self):
        self.renderer.RemoveAllViewProps()
        self.volume = self.mapper = self.loaded = None
        self.widget.GetRenderWindow().Render()

    def load(self, loaded):
        self.clear()
        self.loaded = loaded
        spacing = np.linalg.norm(loaded.affine_lps[:3, :3], axis=0)
        image = vtkImageData()
        image.SetDimensions(*reversed(loaded.voxels.shape))
        image.SetSpacing(*spacing)
        image.GetPointData().SetScalars(numpy_to_vtk(loaded.voxels.ravel(order="C"), deep=True))
        self.mapper = vtkFixedPointVolumeRayCastMapper()
        self.mapper.SetInputData(image)
        self.mapper.SetSampleDistance(float(spacing.min()/2))
        self.property = vtkVolumeProperty()
        self.property.SetInterpolationTypeToLinear()
        self.property.ShadeOn()
        self.property.SetAmbient(.3)
        self.property.SetDiffuse(.7)
        self.property.SetSpecular(.15)
        self.volume = vtkVolume()
        self.volume.SetMapper(self.mapper)
        self.volume.SetProperty(self.property)
        matrix = loaded.affine_lps.copy()
        matrix[:3, :3] /= spacing
        transform = vtkMatrix4x4()
        for row in range(4):
            for col in range(4):
                transform.SetElement(row, col, float(matrix[row, col]))
        self.volume.SetUserMatrix(transform)
        self.renderer.AddVolume(self.volume)
        sphere = vtkSphereSource()
        sphere.SetRadius(float(spacing.min()*.6))
        sphere.SetThetaResolution(12)
        sphere.SetPhiResolution(12)
        marker_mapper = vtkPolyDataMapper()
        marker_mapper.SetInputConnection(sphere.GetOutputPort())
        self.marker = vtkActor()
        self.marker.SetMapper(marker_mapper)
        self.marker.GetProperty().SetColor(.3, 1, .8)
        self.renderer.AddActor(self.marker)
        sample = loaded.voxels.ravel()[::max(1, loaded.voxels.size//262144)]
        self.low, self.high = map(float, np.percentile(sample, [.5, 99.5]))
        self.high = max(self.high, self.low+1)
        self.reset()

    def reset(self):
        if self.volume is None:
            return
        bounds = self.volume.GetBounds()
        center = np.array([(bounds[0]+bounds[1])/2, (bounds[2]+bounds[3])/2, (bounds[4]+bounds[5])/2])
        camera = self.renderer.GetActiveCamera()
        camera.SetViewUp(0, 0, 1)
        camera.SetFocalPoint(*center)
        camera.SetPosition(*(center+np.array([1, -1.6, .55])*max(np.ptp(bounds[0:2]), np.ptp(bounds[4:6]), 1)*2))
        self.renderer.ResetCamera()
        self.renderer.ResetCameraClippingRange()
        self.render()

    def style(self, threshold, opacity, false_color, center, width):
        if self.volume is None:
            return
        low, high = self.low, self.high
        cut = low+(high-low)*threshold/100
        epsilon = max((high-low)*.01, 1e-3)
        alpha = vtkPiecewiseFunction()
        alpha.AddPoint(low-epsilon, 0)
        alpha.AddPoint(cut, 0)
        alpha.AddPoint(cut+epsilon, opacity/100*.10)
        alpha.AddPoint(max(high, cut+2*epsilon), opacity/100*.75)
        color = vtkColorTransferFunction()
        if false_color:
            color.AddRGBPoint(low, .04, .03, .12)
            color.AddRGBPoint(low+(high-low)*.4, .18, .55, .65)
            color.AddRGBPoint(low+(high-low)*.7, .85, .55, .3)
            color.AddRGBPoint(high, 1, .96, .85)
        else:
            a, b = (1, 0) if self.loaded.monochrome1 else (0, 1)
            color.AddRGBPoint(center-width/2, a, a, a)
            color.AddRGBPoint(center+width/2, b, b, b)
        self.property.SetScalarOpacity(alpha)
        self.property.SetColor(color)
        self.render()

    def clipping(self, enabled, index):
        if self.mapper is None:
            return
        self.mapper.RemoveAllClippingPlanes()
        if enabled:
            affine = self.loaded.affine_lps
            point = (affine @ [0, 0, index, 1])[:3]
            normal = -affine[:3, 2]/np.linalg.norm(affine[:3, 2])
            self.plane.SetOrigin(*point)
            self.plane.SetNormal(*normal)
            self.mapper.AddClippingPlane(self.plane)
        self.render()

    def point(self, cursor):
        if self.loaded is not None:
            point = (self.loaded.affine_lps @ [*cursor, 1])[:3]
            self.marker.SetPosition(*point)
            self.render()

    def render(self):
        self.widget.GetRenderWindow().Render()


class MainWindow(QtWidgets.QMainWindow):
    volume_ready = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("4B Imaging 0.2.1 · نمایشگر محلی MRI / CT")
        self.resize(1450, 940)
        self.catalog = self.loaded = None
        self.portal = None
        self.jobs, self.active_job, self.pending_close = [], None, False
        self.received_artifacts = []
        self.document_preview = None
        self.cursor = [0, 0, 0]
        self.orbit_timer, self.cine_timer = QtCore.QTimer(self), QtCore.QTimer(self)
        self.orbit_timer.setInterval(50)
        self.cine_timer.setInterval(140)
        self.orbit_timer.timeout.connect(self.orbit_step)
        self.cine_timer.timeout.connect(self.cine_step)
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)
        heading = QtWidgets.QLabel("4B IMAGING   /   MRI & CT WORKSTATION")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        notice = QtWidgets.QLabel("نمایش محلی دادهٔ اسکن · رنگ شدت، رنگ واقعی بافت نیست · این نسخه تفکیک بافت، تشخیص یا برنامه‌ریزی جراحی انجام نمی‌دهد")
        notice.setWordWrap(True)
        notice.setObjectName("notice")
        layout.addWidget(notice)
        imports = QtWidgets.QHBoxLayout()
        self.file_button, self.folder_button, self.demo_button = [QtWidgets.QPushButton(s) for s in ("بازکردن فایل تصویری / گزارش", "پوشهٔ DICOM", "نمونهٔ ساختگی")]
        for button in (self.file_button, self.folder_button, self.demo_button):
            imports.addWidget(button)
        imports.addStretch()
        self.series_box = QtWidgets.QComboBox()
        self.series_box.setMinimumWidth(310)
        imports.addWidget(self.series_box)
        layout.addLayout(imports)
        network = QtWidgets.QHBoxLayout()
        self.url, self.token = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        self.url.setPlaceholderText("لینک HTTPS صفحهٔ مرکز یا دانلود فایل")
        self.url.setEchoMode(QtWidgets.QLineEdit.PasswordEchoOnEdit)
        self.url.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.token.setPlaceholderText("Bearer token اختیاری")
        self.token.setEchoMode(QtWidgets.QLineEdit.Password)
        self.token.setMaximumWidth(220)
        self.fetch_button, self.cancel_button = QtWidgets.QPushButton("تشخیص لینک و دریافت"), QtWidgets.QPushButton("لغو")
        self.portal_button = QtWidgets.QPushButton("ورود به صفحهٔ مرکز")
        for widget in (self.url, self.portal_button, self.token, self.fetch_button, self.cancel_button):
            network.addWidget(widget, 1 if widget is self.url else 0)
        layout.addLayout(network)
        self.import_notice = QtWidgets.QFrame()
        self.import_notice.setObjectName("importNotice")
        notice_layout = QtWidgets.QVBoxLayout(self.import_notice)
        self.import_notice_title = QtWidgets.QLabel()
        self.import_notice_title.setObjectName("importNoticeTitle")
        self.import_notice_text = QtWidgets.QLabel()
        self.import_notice_text.setWordWrap(True)
        notice_layout.addWidget(self.import_notice_title)
        notice_layout.addWidget(self.import_notice_text)
        notice_actions = QtWidgets.QHBoxLayout()
        self.other_file_button = QtWidgets.QPushButton("انتخاب فایل تصویری یا گزارش")
        self.reopen_received_button = QtWidgets.QPushButton("بازکردن یکی از فایل‌های دریافت‌شده")
        self.help_button = QtWidgets.QPushButton("راهنمای دریافت از مرکز")
        for button in (self.other_file_button, self.reopen_received_button, self.help_button):
            notice_actions.addWidget(button)
        notice_layout.addLayout(notice_actions)
        self.import_notice.hide()
        layout.addWidget(self.import_notice)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        left = QtWidgets.QWidget()
        side = QtWidgets.QVBoxLayout(left)
        side.setContentsMargins(0, 0, 0, 0)
        self.slices = {axis: SlicePanel(title) for axis, title in zip("zyx", ("مقطع شبکه k", "مقطع شبکه j", "مقطع شبکه i"))}
        for axis, panel in self.slices.items():
            side.addWidget(panel, 1)
            panel.changed.connect(lambda value, a=axis: self.slice_changed(a, value))
            panel.selected.connect(lambda u, v, a=axis: self.slice_selected(a, u, v))
        right = QtWidgets.QWidget()
        view_layout = QtWidgets.QVBoxLayout(right)
        view_layout.setContentsMargins(0, 0, 0, 0)
        self.view = VolumeView()
        view_layout.addWidget(self.view, 1)
        hint = QtWidgets.QLabel("چرخش: کشیدن با ماوس چپ  ·  جابه‌جایی: ماوس میانی  ·  بزرگ‌نمایی: چرخ ماوس")
        view_layout.addWidget(hint)
        actions = QtWidgets.QHBoxLayout()
        self.reset_button, self.orbit_button, self.cine_button = [QtWidgets.QPushButton(s) for s in ("بازنشانی نما", "چرخش خودکار", "پخش برش‌ها")]
        self.orbit_button.setCheckable(True)
        self.cine_button.setCheckable(True)
        self.color_box = QtWidgets.QCheckBox("رنگ کاذب شدت")
        self.clip_box = QtWidgets.QCheckBox("برش حجم روی محور k")
        for w in (self.reset_button, self.orbit_button, self.cine_button, self.color_box, self.clip_box):
            actions.addWidget(w)
        view_layout.addLayout(actions)
        knobs = QtWidgets.QGridLayout()
        self.threshold = self.make_slider(0, 99, 30)
        self.opacity = self.make_slider(1, 100, 60)
        self.clip = self.make_slider(0, 63, 32)
        self.window_center = QtWidgets.QDoubleSpinBox()
        self.window_center.setRange(-1e9, 1e9)
        self.window_width = QtWidgets.QDoubleSpinBox()
        self.window_width.setRange(.01, 2e9)
        for col, (title, widget) in enumerate((("آستانهٔ نمایش", self.threshold), ("تراکم نمایش", self.opacity), ("موقعیت برش", self.clip),
                                              ("Window center", self.window_center), ("Window width", self.window_width))):
            knobs.addWidget(QtWidgets.QLabel(title), 0, col)
            knobs.addWidget(widget, 1, col)
        view_layout.addLayout(knobs)
        self.location, self.info = QtWidgets.QLabel(""), QtWidgets.QLabel("یک مجموعهٔ DICOM یا نمونهٔ ساختگی باز کنید.")
        self.location.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.info.setWordWrap(True)
        view_layout.addWidget(self.location)
        view_layout.addWidget(self.info)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([310, 1000])
        layout.addWidget(splitter, 1)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setMaximumHeight(8)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        self.status = QtWidgets.QLabel("آماده · پردازش تصویر محلی است؛ برنامه داده‌ای به سرور 4B-MOS ارسال نمی‌کند.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.import_controls = (self.file_button, self.folder_button, self.demo_button, self.fetch_button, self.portal_button, self.series_box, self.url, self.token,
                                self.other_file_button, self.reopen_received_button, self.help_button)
        self.view_controls = (self.reset_button, self.orbit_button, self.cine_button, self.color_box, self.clip_box,
                              self.threshold, self.opacity, self.clip, self.window_center, self.window_width)
        self.file_button.clicked.connect(self.choose_file)
        self.other_file_button.clicked.connect(self.choose_file)
        self.reopen_received_button.clicked.connect(self.reopen_received)
        self.help_button.clicked.connect(self.show_download_help)
        self.folder_button.clicked.connect(self.choose_folder)
        self.demo_button.clicked.connect(self.load_demo)
        self.fetch_button.clicked.connect(self.load_url)
        self.portal_button.clicked.connect(self.open_portal)
        self.url.returnPressed.connect(self.load_url)
        self.cancel_button.clicked.connect(lambda: self.active_job.cancel.set() if self.active_job else None)
        self.series_box.activated.connect(self.select_series)
        self.reset_button.clicked.connect(self.view.reset)
        self.orbit_button.toggled.connect(lambda enabled: self.orbit_timer.start() if enabled else self.orbit_timer.stop())
        self.cine_button.toggled.connect(lambda enabled: self.cine_timer.start() if enabled else self.cine_timer.stop())
        for knob in (self.threshold, self.opacity):
            knob.valueChanged.connect(self.update_style)
        self.color_box.toggled.connect(self.update_style)
        self.clip_box.toggled.connect(self.update_clip)
        self.clip.valueChanged.connect(self.update_clip)
        for knob in (self.window_center, self.window_width):
            knob.valueChanged.connect(self.window_changed)
        self.busy(False)

        self.save_received_action = QtGui.QAction("ذخیرهٔ فایل دریافت‌شده…", self)
        self.save_received_action.triggered.connect(self.save_received)
        self.inventory_action = QtGui.QAction("ذخیرهٔ فهرست فنی دریافت‌ها…", self)
        self.inventory_action.triggered.connect(self.save_inventory)
        received_menu = self.menuBar().addMenu("فایل‌های دریافت‌شده")
        self.reopen_received_action = received_menu.addAction("بازکردن فایل دریافت‌شده…")
        self.reopen_received_action.triggered.connect(self.reopen_received)
        received_menu.addAction(self.save_received_action)
        received_menu.addAction(self.inventory_action)

    @staticmethod
    def make_slider(low, high, value):
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(low, high)
        slider.setValue(value)
        return slider

    def busy(self, enabled):
        for control in self.import_controls:
            control.setEnabled(not enabled)
        for control in self.view_controls:
            control.setEnabled(not enabled and self.loaded is not None)
        self.cancel_button.setEnabled(enabled)
        self.progress_bar.setRange(0, 0 if enabled else 1)
        self.progress_bar.setValue(0 if enabled else 1)

    def start_job(self, operation, callback, on_failure=None):
        if self.active_job is not None:
            return
        self.busy(True)
        job = Job(operation, self)
        self.active_job = job
        self.jobs.append(job)
        def ready(value):
            self.active_job = None
            self.busy(False)
            if not self.pending_close:
                callback(value)
        def failed(code):
            self.active_job = None
            self.busy(False)
            self.status.setText(MESSAGES.get(code, "ورودی قابل نمایش نیست؛ خروجی DICOM و محدودیت‌های این نسخه را بررسی کنید.")+f"  [{code}]")
            if not self.pending_close and on_failure:
                on_failure(code)
        def finished():
            self.jobs.remove(job)
            job.deleteLater()
            if self.pending_close and not self.jobs:
                self.close()
        job.ready.connect(ready)
        job.failed.connect(failed)
        job.finished.connect(finished)
        job.start()

    def clear(self):
        self.import_notice.hide()
        if self.document_preview is not None:
            self.document_preview.close()
            self.document_preview = None
        self.orbit_button.setChecked(False)
        self.cine_button.setChecked(False)
        self.loaded = self.catalog = None
        self.series_box.clear()
        self.view.clear()
        for panel in self.slices.values():
            panel.canvas.image = None
            panel.canvas.update()
            panel.slider.setEnabled(False)
            panel.value.setText("—")
        self.info.setText("در حال بررسی ورودی؛ کامل‌بودن acquisition با فایل‌های موجود اثبات نمی‌شود.")
        self.location.clear()

    def import_source(self, operation):
        if self.active_job is not None:
            return
        self.clear()
        self.status.setText("در حال دریافت و بررسی DICOM؛ پردازش روی همین رایانه انجام می‌شود…")
        self.start_job(operation, self.catalog_ready)

    def choose_file(self):
        name, _ = QtWidgets.QFileDialog.getOpenFileName(self, "انتخاب فایل تصویری یا گزارش", "", "All files (*)")
        if name:
            self.received_artifacts.clear()
            self.import_received(lambda cancel: receive(read_artifact(name), cancel=cancel))

    def choose_folder(self):
        name = QtWidgets.QFileDialog.getExistingDirectory(self, "انتخاب پوشهٔ DICOM")
        if name:
            self.received_artifacts.clear()
            from .volume import scan
            self.import_source(lambda cancel: scan(open_local(Path(name), cancel=cancel), cancel=cancel))

    def load_url(self):
        url, token = self.url.text().strip(), self.token.text()
        self.url.clear()
        self.token.clear()
        self.received_artifacts.clear()
        def ready(artifact):
            if artifact.processing_code == "portal_page":
                self.received_ready(artifact)
                self.show_portal(url, clear_artifacts=False)
            else:
                self.received_ready(artifact)
        if self.active_job is not None:
            return
        self.clear()
        self.start_job(lambda cancel: receive(download_bytes(url, bearer_token=token, cancel=cancel), cancel=cancel), ready,
                       lambda code: self.show_portal(url) if code == "authentication_required" else None)

    def open_portal(self):
        url = self.url.text().strip()
        self.url.clear()
        self.token.clear()
        self.show_portal(url)

    def show_portal(self, url, *, clear_artifacts=True):
        from .sources import validate_https_url
        from .portal import PortalWindow
        if clear_artifacts:
            self.received_artifacts.clear()
        try:
            validate_https_url(url)
        except ImportFailure as error:
            self.status.setText(MESSAGES.get(str(error), "لینک HTTPS صفحهٔ مرکز لازم است."))
            return
        if self.portal is not None:
            self.portal.dispose()
        self.portal = PortalWindow(self)
        self.portal.downloaded.connect(self.portal_download)
        self.portal.open_url(url)

    def portal_download(self, path, temporary):
        if self.active_job is not None:
            temporary.cleanup()
            self.status.setText("یک ورودی در حال پردازش است؛ پس از پایان دوباره دانلود کنید.")
            return
        def operation(cancel):
            try:
                return receive(read_artifact(path), cancel=cancel)
            finally:
                temporary.cleanup()
        self.import_received(operation)

    def import_received(self, operation):
        if self.active_job is not None:
            return
        self.clear()
        self.start_job(operation, self.received_ready)

    def received_ready(self, artifact, *, remember=True):
        from .sources import MAX_INPUT_BYTES
        if remember:
            while self.received_artifacts and sum(len(a.payload) for a in self.received_artifacts)+len(artifact.payload) > MAX_INPUT_BYTES:
                self.received_artifacts.pop(0)
            self.received_artifacts.append(artifact)
        if artifact.catalog is not None:
            self.catalog_ready(artifact.catalog)
            return
        if artifact.processing_code in {"executable_requires_image_export", "embedded_archive_requires_image_export"}:
            self.import_notice_title.setText("فایل اجرایی مرکز دریافت شد؛ هنوز تصویر قابل نمایش نداریم")
            self.import_notice_text.setText(
                "این فایل می‌تواند برنامهٔ مشاهده، دانلودکننده یا بستهٔ اختصاصی مرکز باشد. "
                "ZIP جاسازی‌شده بدون اجرای برنامه بررسی می‌شود؛ در این ورودی دادهٔ حجمی قابل‌خواندن پیدا نشد. "
                "در صفحهٔ مرکز گزینهٔ «تصاویر / DICOM / ZIP / Export» یا گزارش PDF را انتخاب کنید. "
                "اگر فایل تصویری قبلاً دریافت شده، آن را از فهرست دریافت‌ها باز کنید.")
            self.import_notice.show()
        self.info.setText(f"فایل دریافت شد · قالب: {artifact.inventory.kind} · {len(artifact.payload)/1024/1024:.2f} MiB\n"
                          "قالب از محتوای فایل تشخیص داده شده؛ دریافت فایل به معنی اعتبار بالینی آن نیست.")
        self.status.setText("فایل از منوی «فایل‌های دریافت‌شده» قابل ذخیره است. "
                            "این قالب وارد پردازشگر حجم DICOM نمی‌شود. ["+artifact.processing_code+"]")
        if artifact.inventory.kind in {"pdf", "png", "jpeg", "gif", "tiff", "bmp", "webp"}:
            self.preview_document(artifact)

    def reopen_received(self):
        if self.active_job is not None or not self.received_artifacts:
            return
        choices = [f"{i+1} · {a.inventory.kind} · {len(a.payload)} bytes" for i, a in enumerate(self.received_artifacts)]
        selected, ok = QtWidgets.QInputDialog.getItem(self, "فایل دریافت‌شده", "انتخاب فایل برای نمایش", choices, 0, False)
        if ok:
            artifact = self.received_artifacts[choices.index(selected)]
            self.clear()
            self.received_ready(artifact, remember=False)

    def show_download_help(self):
        QtWidgets.QMessageBox.information(self, "راهنمای خروجی مرکز",
            "۱. لینک مرکز را در بالای برنامه وارد و «ورود به صفحهٔ مرکز» را انتخاب کنید.\n"
            "۲. کد و رمز را در صفحهٔ خود مرکز وارد کنید.\n"
            "۳. گزینهٔ دانلود تصاویر / DICOM / ZIP / Export یا گزارش PDF را انتخاب کنید.\n"
            "۴. اگر فقط برنامهٔ EXE ارائه می‌شود، خروجی خام یا خروجی قابل دانلود تصاویر را از مرکز بخواهید.\n"
            "بسته‌های دارای ZIP جاسازی‌شده مستقیماً بررسی می‌شوند؛ کد فایل اجرایی اجرا نمی‌شود.")

    def save_received(self):
        if not self.received_artifacts:
            return
        choices = [f"{i+1} · {a.inventory.kind} · {len(a.payload)} bytes" for i, a in enumerate(self.received_artifacts)]
        selected, ok = QtWidgets.QInputDialog.getItem(self, "فایل دریافت‌شده", "انتخاب فایل", choices, len(choices)-1, False)
        if ok:
            name, _ = QtWidgets.QFileDialog.getSaveFileName(self, "ذخیرهٔ اصل فایل؛ ممکن است اطلاعات بیمار داشته باشد", "medical-download.bin")
            if name:
                try:
                    Path(name).write_bytes(self.received_artifacts[choices.index(selected)].payload)
                except OSError:
                    self.status.setText("ذخیرهٔ فایل انجام نشد.")

    def save_inventory(self):
        import json
        if not self.received_artifacts:
            return
        name, _ = QtWidgets.QFileDialog.getSaveFileName(self, "ذخیرهٔ فهرست فنی بدون متن گزارش", "imaging-inventory.json", "JSON (*.json)")
        if name:
            try:
                Path(name).write_text(json.dumps([a.report() for a in self.received_artifacts], indent=2)+"\n", encoding="utf-8")
            except OSError:
                self.status.setText("ذخیرهٔ فهرست انجام نشد.")

    def preview_document(self, artifact):
        dialog = QtWidgets.QDialog(self)
        self.document_preview = dialog
        dialog.finished.connect(lambda: setattr(self, "document_preview", None))
        dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        dialog.setWindowTitle("نمایش اصل فایل دریافت‌شده؛ تأیید پزشکی انجام نشده")
        dialog.resize(850, 750)
        layout = QtWidgets.QVBoxLayout(dialog)
        dialog.buffer = QtCore.QBuffer(dialog)
        dialog.buffer.setData(artifact.payload)
        dialog.buffer.open(QtCore.QIODevice.ReadOnly)
        if artifact.inventory.kind == "pdf":
            from PySide6.QtPdf import QPdfDocument
            from PySide6.QtPdfWidgets import QPdfView
            dialog.document = QPdfDocument(dialog)
            dialog.document.load(dialog.buffer)
            view = QPdfView(dialog)
            view.setDocument(dialog.document)
            view.setPageMode(QPdfView.PageMode.MultiPage)
            layout.addWidget(view)
        else:
            reader = QtGui.QImageReader(dialog.buffer)
            size = reader.size()
            if not size.isValid() or size.width()*size.height() > 64*1024*1024:
                dialog.deleteLater()
                self.status.setText("ابعاد تصویر نامعتبر یا بیشتر از سقف نمایش است؛ اصل فایل قابل ذخیره است.")
                return
            label = QtWidgets.QLabel()
            label.setPixmap(QtGui.QPixmap.fromImage(reader.read()))
            area = QtWidgets.QScrollArea()
            area.setWidget(label)
            layout.addWidget(area)
        dialog.show()

    def load_demo(self):
        self.received_artifacts.clear()
        self.import_source(lambda cancel: demonstration(cancel=cancel))

    def catalog_ready(self, catalog):
        self.catalog = catalog
        for i, series in enumerate(catalog.series):
            title = f"{series.modality} · سری {i+1} · {series.count} برش · {series.shape_yx[1]}×{series.shape_yx[0]}"
            self.series_box.addItem(title+(" · نیازمند بررسی" if series.issues else ""))
        index = next((i for i, series in enumerate(catalog.series) if not series.issues), 0)
        self.series_box.setCurrentIndex(index)
        self.select_series(index)

    def select_series(self, index):
        if self.catalog is None or self.active_job is not None:
            return
        self.orbit_button.setChecked(False)
        self.cine_button.setChecked(False)
        self.loaded = None
        self.view.clear()
        for panel in self.slices.values():
            panel.canvas.image = None
            panel.canvas.update()
            panel.slider.setEnabled(False)
        self.location.clear()
        series = self.catalog.series[index]
        self.info.setText("سری انتخابی در حال بررسی است؛ کامل‌بودن acquisition تأیید نشده است.")
        if series.issues:
            self.busy(False)
            self.status.setText("این سری برای حجم یکنواخت آماده نیست: "+", ".join(series.issues))
            return
        self.status.setText("در حال خواندن پیکسل‌ها و ساخت حجم سه‌بعدی…")
        self.start_job(lambda cancel: load_series(series, cancel=cancel), self.display_volume)

    def display_volume(self, loaded):
        self.loaded = loaded
        self.view.load(loaded)
        nz, ny, nx = loaded.voxels.shape
        self.cursor = [nx//2, ny//2, nz//2]
        for axis, length in zip("xyz", (nx, ny, nz)):
            panel = self.slices[axis]
            panel.slider.blockSignals(True)
            panel.slider.setRange(0, length-1)
            panel.slider.setValue(self.cursor["xyz".index(axis)])
            panel.slider.blockSignals(False)
            panel.slider.setEnabled(True)
        for control, value in ((self.window_center, (self.view.low+self.view.high)/2),
                               (self.window_width, self.view.high-self.view.low),
                               (self.threshold, 70 if loaded.modality == "CT" else 30), (self.clip, nz//2)):
            control.blockSignals(True)
            if control is self.clip:
                control.setMaximum(nz-1)
            control.setValue(value)
            control.blockSignals(False)
        self.clip_box.setChecked(False)
        spacing = np.linalg.norm(loaded.affine_lps[:3, :3], axis=0)
        self.info.setText(f"{loaded.modality} · {nx}×{ny}×{nz} · spacing {spacing[0]:.2f} × {spacing[1]:.2f} × {spacing[2]:.2f} mm\n"
                          "حجم از پیکسل‌های همین سری ساخته شده؛ برچسب آناتومیک تولید نشده و کامل‌بودن مجموعه تأیید نشده است.")
        self.status.setText(f"آماده · پردازش محلی · {self.catalog.ignored_files if self.catalog else 0} فایل غیرتصویری کنار گذاشته شد.")
        self.busy(False)
        self.window_changed()
        self.volume_ready.emit()

    def slice_changed(self, axis, value):
        if self.loaded is not None:
            self.cursor["xyz".index(axis)] = value
            self.update_slices()

    def slice_selected(self, axis, u, v):
        if self.loaded is None:
            return
        nz = self.loaded.voxels.shape[0]
        if axis == "z":
            self.cursor[0:2] = [u, v]
        elif axis == "y":
            self.cursor[0], self.cursor[2] = u, nz-1-v
        else:
            self.cursor[1], self.cursor[2] = u, nz-1-v
        self.update_slices()

    def update_slices(self):
        if self.loaded is None:
            return
        x, y, z = self.cursor
        data = self.loaded.voxels
        sx, sy, sz = np.linalg.norm(self.loaded.affine_lps[:3, :3], axis=0)
        layouts = {"z": (data[z], (x, y), sx/sy), "y": (data[:, y, :][::-1], (x, data.shape[0]-1-z), sx/sz),
                   "x": (data[:, :, x][::-1], (y, data.shape[0]-1-z), sy/sz)}
        for axis, (plane, cross, pixel_ratio) in layouts.items():
            gray = np.clip((plane-self.window_center.value())/self.window_width.value()+.5, 0, 1)
            if self.loaded.monochrome1:
                gray = 1-gray
            gray = np.ascontiguousarray(np.round(gray*255), dtype=np.uint8)
            height, width = gray.shape
            image = QtGui.QImage(gray.data, width, height, gray.strides[0], QtGui.QImage.Format_Grayscale8).copy()
            panel = self.slices[axis]
            panel.canvas.image, panel.canvas.cross, panel.canvas.ratio = image, cross, width/height*pixel_ratio
            panel.canvas.update()
            panel.slider.blockSignals(True)
            panel.slider.setValue(self.cursor["xyz".index(axis)])
            panel.slider.blockSignals(False)
            panel.value.setText(f"{panel.slider.value()+1} / {panel.slider.maximum()+1}")
        point = (self.loaded.affine_lps @ [x, y, z, 1])[:3]
        self.location.setText(f"LPS [ {point[0]:.2f}, {point[1]:.2f}, {point[2]:.2f} ] mm · voxel {data[z,y,x]:.2f}")
        self.view.point(self.cursor)

    def window_changed(self):
        self.update_slices()
        self.update_style()

    def update_style(self):
        self.view.style(self.threshold.value(), self.opacity.value(), self.color_box.isChecked(),
                        self.window_center.value(), self.window_width.value())

    def update_clip(self):
        self.view.clipping(self.clip_box.isChecked(), self.clip.value())

    def orbit_step(self):
        if self.loaded is not None:
            self.view.renderer.GetActiveCamera().Azimuth(1.5)
            self.view.renderer.ResetCameraClippingRange()
            self.view.render()

    def cine_step(self):
        if self.loaded is not None:
            slider = self.slices["z"].slider
            slider.setValue((slider.value()+1) % (slider.maximum()+1))

    def closeEvent(self, event):
        self.orbit_timer.stop()
        self.cine_timer.stop()
        if self.jobs:
            self.pending_close = True
            for job in self.jobs:
                job.cancel.set()
            self.status.setText("در حال توقف خواندن؛ پنجره پس از پایان درخواست جاری بسته می‌شود…")
            event.ignore()
            return
        self.catalog = self.loaded = None
        if self.portal is not None:
            self.portal.dispose()
            self.portal = None
        self.url.clear()
        self.token.clear()
        self.view.widget.Finalize()
        event.accept()


STYLE = """
QWidget { background:#0c1522; color:#e6edf6; font-family:Tahoma,'Segoe UI'; font-size:12px; }
QLabel#heading { color:#71dec8; font-size:21px; font-weight:600; padding:9px; }
QLabel#notice { background:#24271f; color:#ddcfac; padding:10px; border-radius:6px; }
QFrame#importNotice { background:#293125; border:1px solid #7c9064; border-radius:6px; }
QLabel#importNoticeTitle { color:#f4e7ae; font-weight:bold; font-size:15px; }
QPushButton { background:#1b3344; border:1px solid #365165; padding:9px 13px; border-radius:5px; }
QPushButton:hover { background:#28506a; } QPushButton:checked { background:#286353; }
QPushButton:disabled { color:#607586; background:#142332; }
QLineEdit,QComboBox,QDoubleSpinBox { background:#101e2f; border:1px solid #344b61; padding:8px; border-radius:4px; }
QGroupBox { border:1px solid #2c4258; border-radius:7px; margin-top:14px; padding:8px; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 5px; color:#91b4c9; }
QSlider::groove:horizontal { height:5px; background:#284252; border-radius:2px; }
QSlider::handle:horizontal { background:#65d9bf; width:13px; margin:-5px 0; border-radius:5px; }
QProgressBar { border:0; background:#142638; } QProgressBar::chunk { background:#65d9bf; }
"""
