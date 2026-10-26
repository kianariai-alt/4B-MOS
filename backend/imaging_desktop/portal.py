"""Private portal login, explicit-link discovery and content-neutral downloads.

The medical center serves its own page. The user enters credentials directly in
that page. Only explicit download links are automated; no form submission.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6 import QtCore, QtWidgets
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView

from .sources import MAX_INPUT_BYTES, validate_https_url
from .discovery import DISCOVERY_SCRIPT, discover_downloads


class SecureRequests(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        # blob/data are necessary for portal-generated downloads and inline images.
        # Local files, cleartext HTTP, custom OS protocols and FTP are not opened.
        if info.requestUrl().scheme().lower() not in {"https", "blob", "data", "about"}:
            info.block(True)


class PortalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if is_main_frame and url.toString() != "about:blank":
            try:
                validate_https_url(url.toString())
            except ValueError:
                return False
        return True

    def javaScriptConsoleMessage(self, level, message, line, source):
        # Portal console messages can contain identifiers or signed URLs.
        pass


class PortalWindow(QtWidgets.QDialog):
    downloaded = QtCore.Signal(object, object)  # Path, TemporaryDirectory ownership
    notice = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ورود مستقیم به صفحهٔ مرکز تصویربرداری")
        self.resize(1120, 820)
        self.active_downloads = {}
        self.disposing = False
        self.attempted_urls = set()
        self.inspecting = False
        self.discovery_timer = QtCore.QTimer(self)
        self.discovery_timer.setInterval(1500)
        self.discovery_timer.timeout.connect(self.inspect_downloads)
        self.profile = QWebEngineProfile(self)  # unnamed => off-the-record
        assert self.profile.isOffTheRecord()
        self.profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        self.interceptor = SecureRequests(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.web = QWebEngineView(self)
        self.page = PortalPage(self.profile, self.web)
        self.web.setPage(self.page)
        settings = self.page.settings()
        for attribute in (QWebEngineSettings.JavascriptCanAccessClipboard, QWebEngineSettings.LocalContentCanAccessFileUrls,
                          QWebEngineSettings.LocalContentCanAccessRemoteUrls, QWebEngineSettings.AllowRunningInsecureContent):
            settings.setAttribute(attribute, False)
        self.page.certificateError.connect(lambda error: error.rejectCertificate())
        self.page.featurePermissionRequested.connect(lambda origin, feature: self.page.setFeaturePermission(
            origin, feature, QWebEnginePage.PermissionDeniedByUser))
        self.page.newWindowRequested.connect(lambda request: request.openIn(self.page))
        self.profile.downloadRequested.connect(self.accept_download)
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel("کد و رمز را فقط در صفحهٔ خودِ مرکز وارد کنید. دریافت خودکار، لینک‌های مشخص دانلود را پس از ورود پیدا می‌کند. "
                               "همهٔ قالب‌ها دریافت می‌شوند؛ عکس، گزارش و فیلم به پردازشگر مخصوص خود نیاز دارند. "
                               "دادهٔ دانلودی موقتاً روی همین رایانه نوشته و پس از خواندن حذف می‌شود.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.automatic = QtWidgets.QCheckBox("دریافت خودکار لینک‌های دانلود همین مرکز (حداکثر ۸ فایل در این جلسه)")
        self.automatic.setChecked(True)
        layout.addWidget(self.automatic)
        layout.addWidget(self.web, 1)
        self.status = QtWidgets.QLabel("مرورگر خصوصی این جلسه؛ ورود یا تاریخچه برای جلسه بعد نگه داشته نمی‌شود.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def open_url(self, url):
        validate_https_url(url)
        self.attempted_urls.clear()
        self.web.setUrl(QtCore.QUrl(url))
        self.show()
        self.raise_()
        self.discovery_timer.start()

    def inspect_downloads(self):
        if (self.disposing or not self.isVisible() or not self.automatic.isChecked() or self.inspecting
                or self.active_downloads or getattr(self.parent(), "active_job", None) is not None
                or len(self.attempted_urls) >= 8):
            return
        page_url = self.page.url().toString()
        try:
            validate_https_url(page_url)
        except ValueError:
            return
        self.inspecting = True
        def inspected(anchors):
            self.inspecting = False
            if (self.disposing or not self.isVisible() or not self.automatic.isChecked()
                    or self.active_downloads or self.page.url().toString() != page_url):
                return
            result = discover_downloads(page_url, anchors)
            candidate = next((url for url in result.urls if url not in self.attempted_urls), None)
            if candidate is not None:
                self.attempted_urls.add(candidate)
                # Ephemeral browser cookies stay in the browser; no copying.
                self.page.download(QtCore.QUrl(candidate), "medical-download.bin")
            elif not self.attempted_urls:
                self.status.setText("در انتظار ورود یا لینک دانلود مشخص؛ دکمهٔ اختصاصی دانلود را می‌توانید در همین صفحه انتخاب کنید.")
        self.page.runJavaScript(DISCOVERY_SCRIPT, inspected)

    def accept_download(self, request):
        if self.active_downloads:
            request.cancel()
            self.status.setText("یک دانلود در حال انجام است؛ پس از پایان آن دوباره انتخاب کنید.")
            return
        if request.totalBytes() > MAX_INPUT_BYTES or request.isSavePageDownload():
            request.cancel()
            self.status.setText("دانلود از سقف این نسخه بیشتر است یا ذخیرهٔ صفحه است.")
            return
        temporary = TemporaryDirectory(prefix="4b-imaging-portal-")
        path = Path(temporary.name)/"incoming.bin"  # bytes determine the format
        request.setDownloadDirectory(temporary.name)
        request.setDownloadFileName(path.name)
        self.active_downloads[request.id()] = (request, temporary)
        request.receivedBytesChanged.connect(lambda: self.download_progress(request))
        request.stateChanged.connect(lambda state: self.download_state(request, state))
        request.accept()
        self.status.setText("دانلود انتخاب‌شده از مرکز در حال دریافت است…")

    def download_progress(self, request):
        if request.receivedBytes() > MAX_INPUT_BYTES:
            request.cancel()
        else:
            self.status.setText(f"دریافت {request.receivedBytes()/1024/1024:.1f} MiB · سقف ۵۱۲ MiB")

    def download_state(self, request, state):
        if state not in (QWebEngineDownloadRequest.DownloadCompleted, QWebEngineDownloadRequest.DownloadCancelled,
                         QWebEngineDownloadRequest.DownloadInterrupted):
            return
        pair = self.active_downloads.pop(request.id(), None)
        if pair is None:
            return
        _, temporary = pair
        if state == QWebEngineDownloadRequest.DownloadCompleted and not self.disposing:
            self.status.setText("دانلود تمام شد؛ قالب محتوا بررسی و فایل موقت پس از خواندن حذف می‌شود.")
            self.downloaded.emit(Path(temporary.name)/"incoming.bin", temporary)
        else:
            temporary.cleanup()
            self.status.setText("دانلود متوقف شد؛ دادهٔ ناقص برای بازسازی استفاده نمی‌شود.")
        if self.disposing and not self.active_downloads:
            self.finish_dispose()

    def dispose(self):
        self.disposing = True
        self.close()
        if not self.active_downloads:
            self.finish_dispose()

    def finish_dispose(self):
        self.web.stop()
        # Pages must be destroyed before their private profile.
        self.page.deleteLater()
        self.profile.deleteLater()
        self.deleteLater()

    def closeEvent(self, event):
        self.discovery_timer.stop()
        for request, _ in list(self.active_downloads.values()):
            request.cancel()
        self.page.setUrl(QtCore.QUrl("about:blank"))
        self.profile.cookieStore().deleteAllCookies()
        self.profile.clearHttpCache()
        event.accept()
