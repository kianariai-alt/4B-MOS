"""Conservative browser adapter for explicit downloads on authenticated portals.

The center's page remains responsible for authentication. This adapter neither
reads password inputs nor submits forms, clicks arbitrary buttons or guesses APIs.
"""

from dataclasses import dataclass, field
import re
from urllib.parse import unquote, urljoin, urlsplit

from .sources import ImportFailure, validate_https_url


DOWNLOAD_SUFFIXES = frozenset({
    "dcm", "dicom", "zip", "gz", "tgz", "tar", "7z", "rar", "nii", "nrrd", "mha", "mhd",
    "pdf", "png", "jpg", "jpeg", "gif", "tif", "tiff", "bmp", "webp", "heic", "heif",
    "mp4", "mov", "avi", "webm", "mkv", "mpeg", "mpg", "doc", "docx", "rtf", "txt", "csv", "json", "xml",
})


@dataclass(frozen=True)
class DiscoveryResult:
    urls: tuple[str, ...] = field(default=(), repr=False)
    status: str = "manual_export_required"
    adapter_version: str = "explicit-download-links-v1"


def is_portal_link(url):
    """Route a patient portal to the browser before any cookie-free request.

    This recognizes only a navigation shape, not a vendor or a working export.
    Queries and credentials are never returned or logged.
    """
    try:
        validate_https_url(url)
        return urlsplit(url).path.lower() == "/patient"
    except (ImportFailure, ValueError, TypeError):
        return False


def discover_downloads(page_url, anchors) -> DiscoveryResult:
    origin = validate_https_url(page_url)
    if type(anchors) is not list or len(anchors) > 200:
        return DiscoveryResult(status="portal_inspection_limit")
    found = {}
    for anchor in anchors:
        if type(anchor) is not dict or anchor.get("visible") is not True:
            continue
        href = anchor.get("href")
        if type(href) is not str or len(href) > 8192:
            continue
        url = urljoin(page_url, href)
        try:
            if validate_https_url(url) != origin:
                continue
        except ImportFailure:
            continue
        # URL suffixes are discovery hints only; incoming bytes decide the format.
        path = unquote(urlsplit(url).path).lower()
        suffix = path.rsplit(".", 1)[-1] if "." in path else ""
        label = anchor.get("text", "")
        if type(label) is not str:
            continue
        explicit = (anchor.get("download") is True or suffix in DOWNLOAD_SUFFIXES
                    or bool(re.search(r"\b(download|export)\b|دانلود|دریافت فایل", label[:300], re.I)))
        if explicit:
            # Keep every explicit format eligible, but fetch image/data exports
            # before viewer/install programs when the center offers both.
            priority = 0 if suffix in {"dcm", "dicom", "zip", "nii", "gz", "nrrd", "mha"} else 1
            if suffix in {"exe", "msi", "com", "bat", "cmd", "ps1", "scr", "dmg", "pkg"}:
                priority = 2
            found[url] = min(priority, found.get(url, priority))
    if len(found) > 8:
        return DiscoveryResult(status="too_many_download_candidates")
    return DiscoveryResult(tuple(sorted(found, key=lambda url:(found[url], url))), "downloads_found" if found else "manual_export_required")


# Read only visible anchor descriptors; never input values, cookies or page text.
DISCOVERY_SCRIPT = """(() => JSON.stringify(Array.from(document.querySelectorAll('a[href]')).slice(0,201).map(a => ({
  href: (a.getAttribute('href') || '').length <= 8192 ? a.getAttribute('href') : null,
  text: (a.innerText || '').slice(0,300),
  download: a.hasAttribute('download'), visible: !!a.getClientRects().length &&
  getComputedStyle(a).visibility !== 'hidden'
}))))()"""
