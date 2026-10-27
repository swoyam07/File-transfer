"""Small, structurally valid media files for tests."""

from __future__ import annotations

import struct
import zlib


def _png_chunk(ctype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF)


def make_png(*, text: bytes | None = None, trailing: bytes = b"") -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    data = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr)
    if text is not None:
        data += _png_chunk(b"tEXt", text)
    data += _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")
    return data + trailing


def _jpeg_segment(marker: int, payload: bytes) -> bytes:
    return bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload


def make_exif(*, orientation: int = 6, extra_ascii: bytes = b"GPS 27.7172N 85.3240E") -> bytes:
    # Little-endian TIFF: IFD0 with Orientation and an ImageDescription string.
    desc_offset = 8 + 2 + 2 * 12 + 4
    tiff = b"II*\x00" + struct.pack("<I", 8)
    tiff += struct.pack("<H", 2)
    tiff += struct.pack("<HHIHH", 0x0112, 3, 1, orientation, 0)
    tiff += struct.pack("<HHII", 0x010E, 2, len(extra_ascii) + 1, desc_offset)
    tiff += struct.pack("<I", 0)
    tiff += extra_ascii + b"\x00"
    return b"Exif\x00\x00" + tiff


def make_jpeg(*, exif: bytes | None = None, comment: bytes | None = None, trailing: bytes = b"") -> bytes:
    data = b"\xff\xd8"
    data += _jpeg_segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    if exif is not None:
        data += _jpeg_segment(0xE1, exif)
    if comment is not None:
        data += _jpeg_segment(0xFE, comment)
    data += _jpeg_segment(0xDB, b"\x00" + bytes(range(1, 65)))
    data += _jpeg_segment(0xC0, b"\x08\x00\x01\x00\x01\x01\x01\x11\x00")
    data += _jpeg_segment(0xC4, b"\x00" + b"\x01" + b"\x00" * 15 + b"\x00")
    data += _jpeg_segment(0xDA, b"\x01\x01\x00\x00\x3f\x00")
    data += b"\x12\x34\xff\x00\x56"  # entropy data with a stuffed 0xFF00
    data += b"\xff\xd9"
    return data + trailing


def _box(btype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body) + 8) + btype + body


def make_mp4(*, brand: bytes = b"isom", trailing: bytes = b"") -> bytes:
    ftyp = _box(b"ftyp", brand + b"\x00\x00\x02\x00" + brand + b"mp41")
    moov = _box(b"moov", _box(b"mvhd", b"\x00" * 100))
    mdat = _box(b"mdat", b"\x00\x01\x02\x03" * 64)
    return ftyp + moov + mdat + trailing


def _ebml(element_id: bytes, body: bytes) -> bytes:
    size = len(body)
    assert size < 2 ** 56
    return element_id + bytes([0x01]) + size.to_bytes(7, "big") + body


def make_mkv(*, doctype: bytes = b"matroska", attachment: bool = False, trailing: bytes = b"") -> bytes:
    header = _ebml(b"\x1a\x45\xdf\xa3", _ebml(b"\x42\x82", doctype))
    children = _ebml(b"\x15\x49\xa9\x66", b"\x00" * 16)  # Info
    if attachment:
        children += _ebml(b"\x19\x41\xa4\x69", b"MZ payload")
    children += _ebml(b"\x1f\x43\xb6\x75", b"\x00" * 64)  # Cluster
    return header + _ebml(b"\x18\x53\x80\x67", children) + trailing


def make_avi(*, trailing: bytes = b"") -> bytes:
    hdrl = b"LIST" + struct.pack("<I", 4 + 8) + b"hdrl" + b"avih" + struct.pack("<I", 0)
    movi = b"LIST" + struct.pack("<I", 4 + 4) + b"movi" + b"\x00" * 4
    body = b"AVI " + hdrl + movi
    return b"RIFF" + struct.pack("<I", len(body)) + body + trailing


def make_mp3(*, frames: int = 3, id3: bytes | None = None, trailing: bytes = b"") -> bytes:
    # MPEG-1 layer III, 128 kbps, 44.1 kHz, no padding: 417-byte frames.
    frame = b"\xff\xfb\x90\x00" + b"\x55" * 413
    data = b""
    if id3 is not None:
        size = len(id3)
        syncsafe = bytes(((size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F))
        data += b"ID3\x03\x00\x00" + syncsafe + id3
    return data + frame * frames + trailing


def make_pdf(*, extra_objects: bytes = b"", trailing: bytes = b"") -> bytes:
    content = b"BT /F1 12 Tf 72 712 Td (Hello /JS world) Tj ET"
    return (
        b"%PDF-1.7\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream\nendobj\n"
        + extra_objects
        + b"trailer\n<< /Root 1 0 R /Info << /Title (A /JavaScript guide) >> >>\n%%EOF\n"
        + trailing
    )


def make_pdf_object_stream(objects: bytes) -> bytes:
    body = zlib.compress(objects)
    return (
        b"9 0 obj\n<< /Type /ObjStm /N 1 /First 4 /Filter /FlateDecode /Length "
        + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream\nendobj\n"
    )
