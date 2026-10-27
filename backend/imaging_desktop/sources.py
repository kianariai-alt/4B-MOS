"""Bounded desktop imports. No patient identifiers, paths or URLs in reports/logs."""

from dataclasses import dataclass, field
from io import BytesIO
import os
from pathlib import Path, PurePosixPath
import ssl
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
import zipfile

from backend.app.imaging_intelligence.intake import is_embedded_zip


MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_FILES = 512


class ImportFailure(ValueError):
    """Only a static code is allowed to cross the worker/UI boundary."""


def check_cancel(cancel=None):
    if cancel is not None and cancel.is_set():
        raise ImportFailure("cancelled")


@dataclass(frozen=True)
class SourceFiles:
    files: tuple[bytes, ...] = field(repr=False)
    ignored_files: int = 0


def validate_https_url(url):
    try:
        parts = urlsplit(url)
        if (not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 33 for c in url)
                or parts.scheme != "https" or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.fragment or (parts.port is not None and not 1 <= parts.port <= 65535)):
            raise ValueError()
        return parts.hostname.lower(), parts.port or 443
    except (ValueError, TypeError, AttributeError):
        raise ImportFailure("https_download_link_required") from None


class _SameOriginRedirect(HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if validate_https_url(newurl) != validate_https_url(req.full_url):
            raise ImportFailure("cross_host_redirect_blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_stream(response, *, cancel=None, progress=None, allow_any_format=False):
    """The response can be a real HTTPS stream or a byte stream in unit tests."""
    if getattr(response, "status", 200) != 200:
        raise ImportFailure("download_failed")
    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
        raise ImportFailure("encoded_download_not_supported")
    kind = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    if not allow_any_format and kind in {"text/html", "application/xhtml+xml", "application/json"}:
        raise ImportFailure("portal_page_requires_dicom_download")
    try:
        length = int(response.headers.get("Content-Length", "0"))
    except ValueError:
        raise ImportFailure("invalid_download_length") from None
    if not 0 <= length <= MAX_INPUT_BYTES:
        raise ImportFailure("download_size_limit")
    data, count, started = BytesIO(), 0, time.monotonic()
    while True:
        check_cancel(cancel)
        if time.monotonic()-started > 180:
            raise ImportFailure("download_timeout")
        chunk = response.read(min(256*1024, MAX_INPUT_BYTES-count+1))
        if not chunk:
            break
        count += len(chunk)
        if count > MAX_INPUT_BYTES:
            raise ImportFailure("download_size_limit")
        data.write(chunk)
        if progress:
            progress(count, length)
    if length and count != length:
        raise ImportFailure("truncated_download")
    return data.getvalue()


def download_bytes(url, *, bearer_token="", cancel=None, progress=None, allow_any_format=True):
    check_cancel(cancel)
    validate_https_url(url)
    if not isinstance(bearer_token, str) or len(bearer_token) > 4096 or "\r" in bearer_token or "\n" in bearer_token:
        raise ImportFailure("invalid_access_token")
    headers = {"Accept": "*/*", "Accept-Encoding": "identity", "User-Agent": "4B-Imaging-Desktop/0.2"}
    if bearer_token:
        headers["Authorization"] = "Bearer " + bearer_token
    # Fresh opener: no shared cookies, cache, browsing history or credentials.
    opener = build_opener(_SameOriginRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(Request(url, headers=headers), timeout=15) as response:
            raw = _download_stream(response, cancel=cancel, progress=progress, allow_any_format=allow_any_format)
        return raw
    except ImportFailure:
        raise
    except HTTPError as error:
        raise ImportFailure("authentication_required" if error.code in {401, 403} else "download_failed") from None
    except (URLError, OSError, ValueError):
        raise ImportFailure("https_connection_failed") from None


def download(url, *, bearer_token="", cancel=None, progress=None):
    """Compatibility entry point for existing DICOM callers."""
    return unpack(download_bytes(url, bearer_token=bearer_token, cancel=cancel,
                                 progress=progress, allow_any_format=False), cancel=cancel)


def read_artifact(path):
    """Receive any regular local file without assuming its extension or format."""
    return _read_file(Path(path), limit=MAX_INPUT_BYTES)


def unpack(raw, *, cancel=None):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_INPUT_BYTES:
        raise ImportFailure("input_size_limit")
    if raw[:4] != b"PK\x03\x04" and not is_embedded_zip(raw):
        if len(raw) <= MAX_FILE_BYTES and raw[128:132] == b"DICM":
            return SourceFiles((raw,))
        if raw.lstrip()[:1] == b"<":
            raise ImportFailure("portal_page_requires_dicom_download")
        raise ImportFailure("dicom_or_zip_required")
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES+32:
                raise ImportFailure("file_count_limit")
            payloads, total, ignored = [], 0, 0
            for item in entries:
                check_cancel(cancel)
                path = PurePosixPath(item.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts or ":" in item.filename or stat.S_ISLNK(item.external_attr >> 16):
                    raise ImportFailure("unsafe_archive_entry")
                if item.is_dir():
                    continue
                total += item.file_size
                if (item.flag_bits & 1 or item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                        or item.file_size > MAX_FILE_BYTES or total > MAX_INPUT_BYTES):
                    raise ImportFailure("archive_limits_or_encryption")
                with archive.open(item) as stream:
                    content = stream.read(MAX_FILE_BYTES+1)
                if len(content) != item.file_size or len(content) > MAX_FILE_BYTES:
                    raise ImportFailure("archive_size_mismatch")
                if content[128:132] == b"DICM":
                    payloads.append(content)
                else:
                    ignored += 1
                if len(payloads) > MAX_FILES:
                    raise ImportFailure("file_count_limit")
            if not payloads:
                raise ImportFailure("no_dicom_instances")
            return SourceFiles(tuple(payloads), ignored)
    except ImportFailure:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        raise ImportFailure("invalid_zip") from None


def _read_file(path, *, limit=None):
    limit = MAX_FILE_BYTES if limit is None else limit
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or path.is_symlink()
                or getattr(info, "st_file_attributes", 0) & 0x400 or info.st_size > limit):
            raise ImportFailure("regular_file_or_size_required")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            current = os.fstat(stream.fileno())
            if (not stat.S_ISREG(current.st_mode) or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)):
                raise ImportFailure("regular_file_or_size_required")
            raw = stream.read(limit+1)
        if len(raw) > limit:
            raise ImportFailure("input_size_limit")
        return raw
    except ImportFailure:
        raise
    except OSError:
        raise ImportFailure("local_file_unavailable") from None


def open_local(path, *, cancel=None):
    check_cancel(cancel)
    path = Path(path)
    if not path.is_dir():
        # ZIP archives may be larger than an individual DICOM instance.
        if path.suffix.lower() == ".zip":
            return unpack(_read_file(path, limit=MAX_INPUT_BYTES), cancel=cancel)
        return unpack(_read_file(path), cancel=cancel)
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ImportFailure("regular_directory_required")
    payloads, total, ignored, visited, directories = [], 0, 0, 0, 0
    def unavailable(error):
        raise ImportFailure("local_file_unavailable")
    try:
        for root, folders, names in os.walk(path, followlinks=False, onerror=unavailable):
            check_cancel(cancel)
            directories += 1
            if directories > MAX_FILES+32:
                raise ImportFailure("file_count_limit")
            folders[:] = sorted(name for name in folders if not (Path(root)/name).is_symlink()
                                and not (hasattr(Path(root)/name, "is_junction") and (Path(root)/name).is_junction()))
            for name in sorted(names):
                check_cancel(cancel)
                visited += 1
                if visited > MAX_FILES+32:
                    raise ImportFailure("file_count_limit")
                raw = _read_file(Path(root)/name)
                total += len(raw)
                if total > MAX_INPUT_BYTES:
                    raise ImportFailure("input_size_limit")
                if raw[128:132] == b"DICM":
                    payloads.append(raw)
                else:
                    ignored += 1
        if not payloads or len(payloads) > MAX_FILES:
            raise ImportFailure("no_dicom_instances" if not payloads else "file_count_limit")
        return SourceFiles(tuple(payloads), ignored)
    except OSError:
        raise ImportFailure("local_file_unavailable") from None
