"""Content-based intake inventory, independent of Qt, network and clinical rules.

Every byte format may be received. Recognition is a routing hint, never proof
that an object is safe, a valid scan, de-identified, or suitable for diagnosis.
No archive is extracted and no document, script, macro or model is executed.
"""

from collections import Counter
from dataclasses import asdict, dataclass
from io import BytesIO
import gzip
import hashlib
from pathlib import PurePosixPath
import stat
import struct
import tarfile
import zipfile


MAX_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 544
MAX_INSPECTED_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 2


class IntakeError(ValueError):
    """Static error codes only; filenames and document text may contain PHI."""


@dataclass(frozen=True)
class ArtifactInventory:
    kind: str
    byte_count: int
    content_sha256: str
    member_kinds: tuple[tuple[str, int], ...] = ()
    issues: tuple[str, ...] = ()
    schema_version: str = "imaging-artifact-inventory-v1"
    detection_only: bool = True
    patient_identity_verified: bool = False
    clinically_validated: bool = False

    def to_dict(self):
        return asdict(self)


def _kind(raw):
    head = raw[:4096].lstrip(b"\xef\xbb\xbf\x00\t\n\r ")
    if raw[128:132] == b"DICM":
        return "dicom"
    if raw.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"
    if raw.startswith(b"\x1f\x8b"):
        return "gzip"
    if raw[257:263] in (b"ustar\x00", b"ustar "):
        return "tar"
    if raw.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "seven_zip"
    if raw.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")):
        return "rar"
    if (len(raw) >= 348 and raw[344:348] in (b"n+1\x00", b"ni1\x00")
            and (struct.unpack("<I", raw[:4])[0] == 348 or struct.unpack(">I", raw[:4])[0] == 348)):
        return "nifti"
    if raw[4:12] == b"n+2\x00\r\n\x1a\n" and raw[:4] in (struct.pack("<I", 540), struct.pack(">I", 540)):
        return "nifti"
    for signature, kind in ((b"%PDF-", "pdf"), (b"\x89PNG\r\n\x1a\n", "png"),
                            (b"\xff\xd8\xff", "jpeg"), (b"GIF87a", "gif"), (b"GIF89a", "gif"),
                            (b"II*\x00", "tiff"), (b"MM\x00*", "tiff"), (b"BM", "bmp"),
                            (b"NRRD", "nrrd"), (b"{\\rtf", "rtf"),
                            (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole_document"),
                            (b"\x1a\x45\xdf\xa3", "matroska"), (b"\x00\x00\x01\xba", "mpeg")):
        if raw.startswith(signature):
            return kind
    if raw.startswith((b"MZ", b"\x7fELF", b"#!")):
        return "executable"
    if raw[:4] == b"RIFF":
        return {b"WEBP": "webp", b"AVI ": "avi", b"WAVE": "wav"}.get(raw[8:12], "unknown")
    if raw[4:8] == b"ftyp":
        return "iso_media"  # MP4/MOV/HEIF require a container-specific decoder.
    if head.lower().startswith((b"<!doctype html", b"<html", b"<head", b"<body", b"<script")):
        return "html"
    if head.startswith(b"<?xml"):
        return "xml"
    if b"ObjectType = Image" in head or b"ObjectType=Image" in head:
        return "metaimage"
    try:
        text = raw[:65536].decode("utf-8")
        if text.strip() and all(c.isprintable() or c in "\t\n\r" for c in text):
            return "structured_text" if head[:1] in (b"{", b"[") else "text"
    except UnicodeDecodeError:
        pass
    return "unknown"


def _safe_name(name):
    path = PurePosixPath(name.replace("\\", "/"))
    return not (path.is_absolute() or ".." in path.parts or ":" in name or "\x00" in name)


def inventory(raw: bytes, *, _depth=0) -> ArtifactInventory:
    if type(raw) is not bytes or not raw or len(raw) > MAX_BYTES:
        raise IntakeError("artifact_size_limit")
    kind, counts, issues = _kind(raw), Counter(), set()
    if kind in {"rar", "seven_zip"}:
        issues.add("archive_decoder_required")
    if kind in {"unknown", "executable"}:
        issues.add("quarantined_no_processor")
    if kind in {"zip", "gzip", "tar"}:
        if _depth >= MAX_DEPTH:
            issues.add("nested_archive_inspection_limit")
        else:
            try:
                if kind == "gzip":
                    with gzip.GzipFile(fileobj=BytesIO(raw)) as stream:
                        expanded = stream.read(MAX_INSPECTED_BYTES + 1)
                    if len(expanded) > MAX_INSPECTED_BYTES:
                        raise IntakeError("archive_expansion_limit")
                    child = inventory(expanded, _depth=_depth+1)
                    counts[child.kind] += 1
                    counts.update(dict(child.member_kinds))
                    issues.update(child.issues)
                else:
                    archive = (zipfile.ZipFile(BytesIO(raw)) if kind == "zip"
                               else tarfile.open(fileobj=BytesIO(raw), mode="r:"))
                    with archive:
                        entries = archive.infolist() if kind == "zip" else archive
                        expanded, inspected = 0, 0
                        for index, item in enumerate(entries):
                            if index >= MAX_MEMBERS:
                                raise IntakeError("archive_member_limit")
                            name = item.filename if kind == "zip" else item.name
                            if (not _safe_name(name) or (kind == "zip" and stat.S_ISLNK(item.external_attr >> 16))
                                    or (kind == "tar" and not (item.isfile() or item.isdir()))):
                                raise IntakeError("unsafe_archive_entry")
                            if item.is_dir() if kind == "zip" else item.isdir():
                                continue
                            size = item.file_size if kind == "zip" else item.size
                            expanded += size
                            if expanded > MAX_BYTES or size < 0:
                                raise IntakeError("archive_expansion_limit")
                            if kind == "zip" and item.flag_bits & 1:
                                issues.add("encrypted_archive_requires_credentials")
                                continue
                            if kind == "zip" and item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                                issues.add("archive_decoder_required")
                                continue
                            if size == 0:
                                counts["empty"] += 1
                                continue
                            if inspected + size > MAX_INSPECTED_BYTES:
                                issues.add("archive_inspection_byte_limit")
                                continue
                            inspected += size
                            stream = archive.open(item) if kind == "zip" else archive.extractfile(item)
                            with stream:
                                payload = stream.read(size+1)
                            if len(payload) != size:
                                raise IntakeError("archive_size_mismatch")
                            child = inventory(payload, _depth=_depth+1)
                            counts[child.kind] += 1
                            counts.update(dict(child.member_kinds))
                            issues.update(child.issues)
            except IntakeError:
                raise
            except (OSError, EOFError, ValueError, RuntimeError, zipfile.BadZipFile, tarfile.TarError):
                raise IntakeError("invalid_archive") from None
    return ArtifactInventory(kind, len(raw), hashlib.sha256(raw).hexdigest(),
                             tuple(sorted(counts.items())), tuple(sorted(issues)))
