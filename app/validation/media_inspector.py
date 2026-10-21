"""
Structural validation and metadata sanitization for the supported media formats.

Every file is parsed according to its real container structure. A file is only
accepted when:

* its bytes are a well-formed instance of a supported format,
* that format matches the file extension (a PNG renamed to .jpg is rejected),
* there is no data hidden after the end of the container (polyglot files),
* nothing in it looks like an executable or a script (see content_scanner).

The parsers are deliberately strict and fail closed: anything not understood is
rejected rather than allowed.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from app.validation.content_scanner import ContentScanner

# extension -> format family
EXTENSION_FORMATS: dict[str, str] = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".heic": "heif",
    ".heif": "heif",
    ".mp4": "iso_video",
    ".m4v": "iso_video",
    ".mov": "iso_video",
    ".mkv": "matroska",
    ".webm": "webm",
    ".avi": "avi",
}

FORMAT_CATEGORIES: dict[str, str] = {
    "jpeg": "images",
    "png": "images",
    "heif": "images",
    "iso_video": "videos",
    "matroska": "videos",
    "webm": "videos",
    "avi": "videos",
}

SUPPORTED_EXTENSIONS = frozenset(EXTENSION_FORMATS)

# Images are loaded into memory to be parsed and rewritten.
MAX_IMAGE_BYTES = 256 * 1024 * 1024

_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif"}

_ISO_TOP_LEVEL_BOXES = {
    b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"uuid", b"meta", b"pdin",
    b"moof", b"mfra", b"sidx", b"styp", b"emsg", b"prft", b"ssix", b"pnot", b"junk",
    b"idat", b"iinf", b"iloc", b"PICT", b"beam",
}

# PNG ancillary chunks that only describe how pixels are displayed. Everything
# else (tEXt, zTXt, iTXt, eXIf, tIME, unknown private chunks) is dropped.
_PNG_KEEP_ANCILLARY = {
    b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"sBIT", b"bKGD", b"pHYs",
    b"acTL", b"fcTL", b"fdAT",
}
_PNG_CRITICAL = {b"IHDR", b"PLTE", b"IDAT", b"IEND"}

_EBML_ID = 0x1A45DFA3
_EBML_DOCTYPE_ID = 0x4282
_MKV_SEGMENT_ID = 0x18538067
_MKV_ATTACHMENTS_ID = 0x1941A469
_MKV_CLUSTER_ID = 0x1F43B675
_MKV_VOID_ID = 0xEC


class MediaRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(slots=True)
class InspectionResult:
    ok: bool
    reason: str
    format: str | None = None
    category: str | None = None
    warnings: list[str] = field(default_factory=list)


def format_for_extension(extension: str) -> str | None:
    return EXTENSION_FORMATS.get(extension.strip().lower())


def category_for_extension(extension: str) -> str | None:
    fmt = format_for_extension(extension)
    return FORMAT_CATEGORIES.get(fmt) if fmt else None


class MediaInspector:
    """
    strict=True  (receiver): trailing data and embedded metadata blocks are errors.
    strict=False (sender):   trailing data after an image is reported as a
                             warning because sanitize_image() removes it.
    """

    def __init__(self, *, strict: bool = True, content_scan: bool = True) -> None:
        self._strict = strict
        self._content_scan = content_scan

    def inspect(self, path: Path, *, claimed_extension: str) -> InspectionResult:
        claimed_format = format_for_extension(claimed_extension)
        if claimed_format is None:
            return InspectionResult(ok=False, reason="unsupported_extension")

        try:
            if path.is_symlink() or not path.is_file():
                raise MediaRejected("not_a_regular_file")
            size = path.stat().st_size
            if size == 0:
                raise MediaRejected("empty_file")

            with path.open("rb") as handle:
                detected = detect_format(handle.read(64))
                if detected is None:
                    raise MediaRejected("unrecognized_content")
                if detected != claimed_format and not _same_family(detected, claimed_format):
                    raise MediaRejected(f"extension_mismatch:content_is_{detected}")
                handle.seek(0)
                warnings = self._validate(detected, handle, size)

            if self._content_scan and FORMAT_CATEGORIES[detected] == "images":
                # Images are scanned here; videos are scanned while streaming
                # so multi-GB files are not read an extra time.
                finding = ContentScanner.scan_file(path)
                if finding:
                    raise MediaRejected(f"suspicious_content:{finding}")
        except MediaRejected as exc:
            return InspectionResult(ok=False, reason=exc.reason)
        except OSError as exc:
            return InspectionResult(ok=False, reason=f"read_error:{exc.__class__.__name__}")

        return InspectionResult(
            ok=True,
            reason="valid",
            format=detected,
            category=FORMAT_CATEGORIES[detected],
            warnings=warnings,
        )

    def _validate(self, fmt: str, handle: BinaryIO, size: int) -> list[str]:
        if fmt in ("jpeg", "png"):
            if size > MAX_IMAGE_BYTES:
                raise MediaRejected("image_too_large")
            data = handle.read()
            if fmt == "jpeg":
                parsed = parse_jpeg(data)
            else:
                parsed = parse_png(data)
            warnings = []
            if parsed.trailing:
                if self._strict:
                    raise MediaRejected("trailing_data_after_image")
                warnings.append("trailing_data_removed")
            if parsed.has_metadata:
                warnings.append("metadata_removed")
            return warnings
        if fmt == "heif":
            brands = _validate_iso_bmff(handle, size)
            if not brands & _HEIF_BRANDS:
                raise MediaRejected("heif_brand_missing")
            return ["heif_metadata_not_removed"]
        if fmt == "iso_video":
            brands = _validate_iso_bmff(handle, size, require=b"moov")
            if brands & _HEIF_BRANDS:
                raise MediaRejected("extension_mismatch:content_is_heif")
            return []
        if fmt in ("matroska", "webm"):
            _validate_matroska(handle, size, fmt)
            return []
        if fmt == "avi":
            _validate_avi(handle, size)
            return []
        raise MediaRejected("unsupported_format")


def _same_family(detected: str, claimed: str) -> bool:
    # A WebM file is a valid Matroska file, so .mkv may hold either.
    return claimed == "matroska" and detected == "webm"


def detect_format(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        major = head[8:12]
        if major in _HEIF_BRANDS:
            return "heif"
        return "iso_video"
    if len(head) >= 8 and head[4:8] in (b"moov", b"wide", b"mdat", b"free", b"skip", b"pnot"):
        return "iso_video"  # QuickTime files without an ftyp box
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        if b"webm" in head[:64]:
            return "webm"
        return "matroska"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "avi"
    return None


# --------------------------------------------------------------------------- JPEG

@dataclass(slots=True)
class _ParsedImage:
    segments: list[tuple[int, bytes]]  # (marker, raw bytes including marker)
    end: int
    trailing: bool
    has_metadata: bool


def _jpeg_is_kept_segment(marker: int, payload: bytes) -> bool:
    if marker == 0xE0:  # APP0 JFIF / JFXX
        return payload.startswith(b"JFIF\x00") or payload.startswith(b"JFXX\x00")
    if marker == 0xE1:  # APP1: only the orientation-only EXIF written by sanitize_jpeg
        return payload in _ORIENTATION_ONLY_PAYLOADS
    if marker == 0xE2:  # APP2: keep ICC colour profile only
        return payload.startswith(b"ICC_PROFILE\x00")
    if marker == 0xEE:  # APP14 Adobe: needed to decode CMYK/YCCK correctly
        return payload.startswith(b"Adobe")
    if 0xE0 <= marker <= 0xEF or marker == 0xFE:  # other APPn and COM
        return False
    return True


def parse_jpeg(data: bytes) -> _ParsedImage:
    if not data.startswith(b"\xff\xd8"):
        raise MediaRejected("jpeg_missing_soi")

    segments: list[tuple[int, bytes]] = [(0xD8, b"\xff\xd8")]
    pos = 2
    size = len(data)
    seen_frame = False
    seen_scan = False
    has_metadata = False

    while True:
        if pos >= size or data[pos] != 0xFF:
            raise MediaRejected("jpeg_corrupt_marker")
        while pos < size and data[pos] == 0xFF:
            pos += 1
        if pos >= size:
            raise MediaRejected("jpeg_truncated")
        marker = data[pos]
        pos += 1

        if marker == 0xD9:
            segments.append((0xD9, b"\xff\xd9"))
            break
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            segments.append((marker, bytes((0xFF, marker))))
            continue
        if marker in (0x00, 0xD8):
            raise MediaRejected("jpeg_unexpected_marker")

        if pos + 2 > size:
            raise MediaRejected("jpeg_truncated")
        (length,) = struct.unpack(">H", data[pos:pos + 2])
        if length < 2 or pos + length > size:
            raise MediaRejected("jpeg_bad_segment_length")
        start = pos - 2
        payload = data[pos + 2:pos + length]
        pos += length

        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            seen_frame = True
        if 0xE0 <= marker <= 0xEF or marker == 0xFE:
            if not _jpeg_is_kept_segment(marker, payload):
                has_metadata = True

        if marker == 0xDA:
            if not seen_frame:
                raise MediaRejected("jpeg_scan_before_frame")
            seen_scan = True
            # Entropy-coded data runs until the next marker that is neither a
            # stuffed 0xFF00 nor a restart marker.
            scan_end = pos
            while True:
                scan_end = data.find(b"\xff", scan_end)
                if scan_end < 0 or scan_end + 1 >= size:
                    raise MediaRejected("jpeg_truncated_scan")
                nxt = data[scan_end + 1]
                if nxt == 0x00 or 0xD0 <= nxt <= 0xD7 or nxt == 0xFF:
                    scan_end += 1 if nxt == 0xFF else 2
                    continue
                break
            segments.append((marker, data[start:scan_end]))
            pos = scan_end
            continue

        segments.append((marker, data[start:pos]))

    if not seen_frame or not seen_scan:
        raise MediaRejected("jpeg_missing_image_data")

    trailing = any(data[pos:])  # zero padding after EOI is harmless
    return _ParsedImage(segments=segments, end=pos, trailing=trailing, has_metadata=has_metadata)


def _exif_orientation(payload: bytes) -> int | None:
    """Return the EXIF orientation tag (1..8) from an APP1 payload, if present."""
    if not payload.startswith(b"Exif\x00\x00"):
        return None
    tiff = payload[6:]
    if len(tiff) < 8:
        return None
    order = tiff[:2]
    if order == b"II":
        fmt = "<"
    elif order == b"MM":
        fmt = ">"
    else:
        return None
    try:
        (ifd_offset,) = struct.unpack(fmt + "I", tiff[4:8])
        (count,) = struct.unpack(fmt + "H", tiff[ifd_offset:ifd_offset + 2])
        for index in range(min(count, 512)):
            entry = tiff[ifd_offset + 2 + index * 12:ifd_offset + 14 + index * 12]
            if len(entry) < 12:
                return None
            tag, typ, _cnt = struct.unpack(fmt + "HHI", entry[:8])
            if tag == 0x0112 and typ == 3:
                (value,) = struct.unpack(fmt + "H", entry[8:10])
                return value if 1 <= value <= 8 else None
    except struct.error:
        return None
    return None


def _orientation_only_app1(orientation: int) -> bytes:
    # Minimal big-endian TIFF with a single IFD0 entry: Orientation.
    tiff = b"MM\x00\x2a" + struct.pack(">I", 8)
    tiff += struct.pack(">H", 1) + struct.pack(">HHIHH", 0x0112, 3, 1, orientation, 0)
    tiff += struct.pack(">I", 0)
    payload = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


_ORIENTATION_ONLY_PAYLOADS = frozenset(_orientation_only_app1(value)[4:] for value in range(1, 9))


def sanitize_jpeg(data: bytes) -> bytes:
    parsed = parse_jpeg(data)
    orientation = None
    for marker, raw in parsed.segments:
        if marker == 0xE1 and orientation is None:
            orientation = _exif_orientation(raw[4:])
            if raw[4:] in _ORIENTATION_ONLY_PAYLOADS:
                orientation = None  # already clean; kept as-is below

    out = bytearray()
    for index, (marker, raw) in enumerate(parsed.segments):
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out += raw
        elif _jpeg_is_kept_segment(marker, raw[4:]):
            out += raw
        if index == 0 and orientation not in (None, 1):
            # Keep the rotation flag so photos do not appear sideways.
            out += _orientation_only_app1(orientation)
    return bytes(out)


# ---------------------------------------------------------------------------- PNG

def parse_png(data: bytes) -> _ParsedImage:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MediaRejected("png_bad_signature")

    pos = 8
    size = len(data)
    segments: list[tuple[int, bytes]] = []
    has_metadata = False
    seen_idat = False
    first = True

    while True:
        if pos + 12 > size:
            raise MediaRejected("png_truncated")
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        if length > size or pos + 12 + length > size:
            raise MediaRejected("png_bad_chunk_length")
        if not all(65 <= c <= 90 or 97 <= c <= 122 for c in ctype):
            raise MediaRejected("png_bad_chunk_type")
        body = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise MediaRejected("png_crc_mismatch")

        if first:
            if ctype != b"IHDR" or length != 13:
                raise MediaRejected("png_missing_ihdr")
            first = False

        is_critical = 65 <= ctype[0] <= 90
        if is_critical and ctype not in _PNG_CRITICAL:
            raise MediaRejected("png_unknown_critical_chunk")
        if ctype == b"IDAT":
            seen_idat = True
        if not is_critical and ctype not in _PNG_KEEP_ANCILLARY:
            has_metadata = True

        raw = data[pos:pos + 12 + length]
        segments.append((int.from_bytes(ctype, "big"), raw))
        pos += 12 + length
        if ctype == b"IEND":
            break

    if not seen_idat:
        raise MediaRejected("png_missing_image_data")

    trailing = any(data[pos:])
    return _ParsedImage(segments=segments, end=pos, trailing=trailing, has_metadata=has_metadata)


def sanitize_png(data: bytes) -> bytes:
    parsed = parse_png(data)
    out = bytearray(b"\x89PNG\r\n\x1a\n")
    for code, raw in parsed.segments:
        ctype = code.to_bytes(4, "big")
        if ctype in _PNG_CRITICAL or ctype in _PNG_KEEP_ANCILLARY:
            out += raw
    return bytes(out)


def sanitize_image_bytes(data: bytes) -> bytes | None:
    """Return the cleaned image, or None when the format has no sanitizer."""
    fmt = detect_format(data[:64])
    if fmt == "jpeg":
        return sanitize_jpeg(data)
    if fmt == "png":
        return sanitize_png(data)
    return None


# ------------------------------------------------------------------ ISO BMFF (MP4)

def _validate_iso_bmff(handle: BinaryIO, size: int, *, require: bytes | None = None) -> set[bytes]:
    pos = 0
    seen: list[bytes] = []
    brands: set[bytes] = set()

    while pos < size:
        handle.seek(pos)
        header = handle.read(16)
        if len(header) < 8:
            raise MediaRejected("mp4_trailing_data")
        box_size, box_type = struct.unpack(">I4s", header[:8])
        header_len = 8
        if box_size == 1:
            if len(header) < 16:
                raise MediaRejected("mp4_truncated")
            (box_size,) = struct.unpack(">Q", header[8:16])
            header_len = 16
        elif box_size == 0:
            box_size = size - pos

        if not all(0x20 <= c <= 0x7E for c in box_type):
            raise MediaRejected("mp4_bad_box_type")
        if box_size < header_len or pos + box_size > size:
            raise MediaRejected("mp4_bad_box_size")
        if box_type not in _ISO_TOP_LEVEL_BOXES:
            raise MediaRejected(f"mp4_unexpected_box:{box_type.decode('ascii', 'replace')}")

        if box_type == b"ftyp":
            if seen:
                raise MediaRejected("mp4_ftyp_not_first")
            handle.seek(pos + header_len)
            body = handle.read(min(box_size - header_len, 1024))
            if len(body) < 8:
                raise MediaRejected("mp4_bad_ftyp")
            brands.add(body[:4])
            for index in range(8, len(body) - 3, 4):
                brands.add(body[index:index + 4])

        seen.append(box_type)
        pos += box_size

    if require is not None and require not in seen:
        raise MediaRejected(f"mp4_missing_{require.decode()}")
    if b"ftyp" not in seen and b"moov" not in seen:
        raise MediaRejected("mp4_missing_ftyp")
    return brands


# ---------------------------------------------------------------- Matroska / WebM

def _read_vint(handle: BinaryIO, *, keep_marker: bool) -> tuple[int, int, bool]:
    """Return (value, length, is_unknown_size)."""
    first = handle.read(1)
    if not first:
        raise MediaRejected("mkv_truncated")
    b0 = first[0]
    length = 1
    mask = 0x80
    while length <= 8 and not b0 & mask:
        mask >>= 1
        length += 1
    if length > 8:
        raise MediaRejected("mkv_bad_vint")
    rest = handle.read(length - 1)
    if len(rest) != length - 1:
        raise MediaRejected("mkv_truncated")
    value = b0 if keep_marker else b0 & (mask - 1)
    for byte in rest:
        value = (value << 8) | byte
    unknown = not keep_marker and value == (1 << (7 * length)) - 1
    return value, length, unknown


def _validate_matroska(handle: BinaryIO, size: int, fmt: str) -> None:
    handle.seek(0)
    element_id, id_len, _ = _read_vint(handle, keep_marker=True)
    if element_id != _EBML_ID:
        raise MediaRejected("mkv_missing_ebml_header")
    header_size, size_len, unknown = _read_vint(handle, keep_marker=False)
    if unknown or header_size > 4096:
        raise MediaRejected("mkv_bad_ebml_header")
    header_end = id_len + size_len + header_size
    doctype = None
    while handle.tell() < header_end:
        child_id, _, _ = _read_vint(handle, keep_marker=True)
        child_size, _, _ = _read_vint(handle, keep_marker=False)
        body = handle.read(child_size)
        if child_id == _EBML_DOCTYPE_ID:
            doctype = body.rstrip(b"\x00").decode("ascii", "replace")
    if doctype not in ("matroska", "webm"):
        raise MediaRejected("mkv_unknown_doctype")
    if fmt == "webm" and doctype != "webm":
        raise MediaRejected("extension_mismatch:content_is_matroska")

    handle.seek(header_end)
    segment_id, _, _ = _read_vint(handle, keep_marker=True)
    if segment_id != _MKV_SEGMENT_ID:
        raise MediaRejected("mkv_missing_segment")
    segment_size, _, segment_unknown = _read_vint(handle, keep_marker=False)
    segment_start = handle.tell()
    segment_end = size if segment_unknown else segment_start + segment_size
    if segment_end > size:
        raise MediaRejected("mkv_truncated")
    if segment_end < size:
        handle.seek(segment_end)
        if any(handle.read(65536)):
            raise MediaRejected("mkv_trailing_data")

    # Walk the segment's top-level children looking for file attachments,
    # which can carry arbitrary files (including executables).
    pos = segment_start
    while pos < segment_end:
        handle.seek(pos)
        child_id, id_len, _ = _read_vint(handle, keep_marker=True)
        child_size, size_len, child_unknown = _read_vint(handle, keep_marker=False)
        if child_id == _MKV_ATTACHMENTS_ID:
            raise MediaRejected("mkv_contains_attachments")
        if child_unknown:
            if child_id == _MKV_CLUSTER_ID:
                break  # live-streamed file; the remaining data is clusters
            raise MediaRejected("mkv_bad_element_size")
        pos += id_len + size_len + child_size
    if pos > segment_end:
        raise MediaRejected("mkv_bad_element_size")


# ----------------------------------------------------------------------------- AVI

def _validate_avi(handle: BinaryIO, size: int) -> None:
    pos = 0
    first = True
    while pos < size:
        handle.seek(pos)
        header = handle.read(12)
        if len(header) < 12:
            if any(header):
                raise MediaRejected("avi_trailing_data")
            break
        fourcc, chunk_size, form = struct.unpack("<4sI4s", header)
        if fourcc != b"RIFF":
            raise MediaRejected("avi_trailing_data")
        if first:
            if form != b"AVI ":
                raise MediaRejected("avi_bad_form")
            child = handle.read(12)
            if len(child) < 12 or child[:4] != b"LIST" or child[8:12] != b"hdrl":
                raise MediaRejected("avi_missing_header_list")
            first = False
        elif form != b"AVIX":  # OpenDML extension for files over 1 GB
            raise MediaRejected("avi_unexpected_riff")
        end = pos + 8 + chunk_size + (chunk_size & 1)
        if end > size + 1:
            raise MediaRejected("avi_truncated")
        pos = end
