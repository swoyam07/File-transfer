from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from app.models.manifest import FileManifestEntry, TransferManifest
from app.security.auth import AuthError
from app.security.network_policy import NetworkPolicyError, PeerAllowList, resolve_lan_address
from app.security.path_validator import PathSecurityValidator
from app.scanning.scanner import FileScanner
from app.transfer.receiver_service import ReceiverService
from app.transfer.sender_service import SenderService
from app.validation.extension_policy import ExtensionPolicy
from app.validation.media_inspector import MediaInspector, parse_jpeg, sanitize_jpeg, sanitize_mp3, sanitize_png
from app.validation.signature_policy import SignaturePolicy
from tests.unit.media_samples import (
    make_avi, make_exif, make_jpeg, make_mkv, make_mp3, make_mp4, make_pdf, make_pdf_object_stream, make_png,
)

PAIRING_CODE = "test-pairing-code"
EXE_BYTES = b"MZ\x90\x00" + b"\x00" * 60 + b"This program cannot be run in DOS mode.\r\n" + b"\x00" * 64


def _inspect(tmp_path: Path, name: str, data: bytes, *, strict: bool = True):
    path = tmp_path / name
    path.write_bytes(data)
    return MediaInspector(strict=strict).inspect(path, claimed_extension=path.suffix)


# ------------------------------------------------------------- content checks

@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("a.png", make_png()),
        ("a.jpg", make_jpeg(exif=make_exif())),
        ("a.mp4", make_mp4()),
        ("a.mov", make_mp4(brand=b"qt  ")),
        ("a.mkv", make_mkv()),
        ("a.mkv", make_mkv(doctype=b"webm")),
        ("a.webm", make_mkv(doctype=b"webm")),
        ("a.avi", make_avi()),
        ("a.mp3", make_mp3()),
        ("tagged.mp3", make_mp3(id3=b"TIT2\x00\x00\x00\x06\x00\x00\x00Song!")),
        ("cut.mp3", make_mp3()[:-100]),
        # "/JS" and "/JavaScript" inside text strings and page content are just text.
        ("a.pdf", make_pdf()),
        ("packed.pdf", make_pdf(extra_objects=make_pdf_object_stream(b"5 0 << /Type /Font >>"))),
    ],
)
def test_valid_media_accepted(tmp_path: Path, name: str, data: bytes) -> None:
    result = _inspect(tmp_path, name, data)
    assert result.ok, result.reason


@pytest.mark.parametrize(
    ("name", "data", "reason"),
    [
        ("renamed.jpg", make_png(), "extension_mismatch:content_is_png"),
        ("renamed.png", make_jpeg(), "extension_mismatch:content_is_jpeg"),
        ("renamed.mp4", make_mkv(), "extension_mismatch:content_is_matroska"),
        ("renamed.webm", make_mkv(), "extension_mismatch:content_is_matroska"),
        ("photo.mp4", make_mp4(brand=b"heic"), "extension_mismatch:content_is_heif"),
        ("virus.png", EXE_BYTES, "unrecognized_content"),
        ("virus.mp4", EXE_BYTES, "unrecognized_content"),
        ("random.jpg", b"hello world, not an image", "unrecognized_content"),
        ("empty.png", b"", "empty_file"),
        ("polyglot.png", make_png(trailing=EXE_BYTES), "trailing_data_after_image"),
        ("polyglot.jpg", make_jpeg(trailing=b"PK\x03\x04zipdata"), "trailing_data_after_image"),
        ("polyglot.mp4", make_mp4(trailing=b"MZ" + b"\x01" * 3), "mp4_trailing_data"),
        ("polyglot.mkv", make_mkv(trailing=b"\x01" * 16), "mkv_trailing_data"),
        ("attach.mkv", make_mkv(attachment=True), "mkv_contains_attachments"),
        ("script.jpg", make_jpeg(comment=b"<script>alert(1)</script>"), "suspicious_content:html_script"),
        ("php.png", make_png(text=b"Comment\x00<?php system($_GET['c']); ?>"), "suspicious_content:php_code"),
        ("truncated.png", make_png()[:-6], "png_truncated"),
        ("vector.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "unsupported_extension"),
        ("renamed.pdf", make_mp3(), "extension_mismatch:content_is_mp3"),
        ("renamed.mp3", make_pdf(), "extension_mismatch:content_is_pdf"),
        ("virus.mp3", EXE_BYTES, "unrecognized_content"),
        ("virus.pdf", EXE_BYTES, "unrecognized_content"),
        ("polyglot.mp3", make_mp3(trailing=EXE_BYTES), "trailing_data_after_audio"),
        ("script.mp3", make_mp3(id3=b"COMM<script>alert(1)</script>"), "suspicious_content:html_script"),
        ("polyglot.pdf", make_pdf(trailing=EXE_BYTES), "trailing_data_after_document"),
        ("js.pdf", make_pdf(extra_objects=b"5 0 obj << /S /JavaScript /JS (app.alert(1)) >> endobj\n"),
         "pdf_active_content:JavaScript"),
        ("escaped.pdf", make_pdf(extra_objects=b"5 0 obj << /S /J#61vaScript >> endobj\n"),
         "pdf_active_content:JavaScript"),
        ("launch.pdf", make_pdf(extra_objects=b"5 0 obj << /S /Launch /F (cmd.exe) >> endobj\n"),
         "pdf_active_content:Launch"),
        ("attached.pdf", make_pdf(extra_objects=b"5 0 obj << /Type /Filespec /EF << /F 6 0 R >> >> endobj\n"),
         "pdf_active_content:EF"),
        ("hidden.pdf", make_pdf(extra_objects=make_pdf_object_stream(b"5 0 << /S /JavaScript /JS 6 0 R >>")),
         "pdf_active_content:JavaScript"),
        ("encrypted.pdf", make_pdf(extra_objects=b"5 0 obj << /Encrypt 7 0 R >> endobj\n"),
         "pdf_active_content:Encrypt"),
    ],
)
def test_dangerous_or_invalid_files_rejected(tmp_path: Path, name: str, data: bytes, reason: str) -> None:
    result = _inspect(tmp_path, name, data)
    assert result.ok is False
    assert result.reason == reason


def test_corrupted_png_crc_rejected(tmp_path: Path) -> None:
    data = bytearray(make_png())
    data[43] ^= 0xFF  # inside the IDAT chunk data
    assert _inspect(tmp_path, "bad.png", bytes(data)).reason == "png_crc_mismatch"


def test_sender_mode_reports_trailing_data_instead_of_rejecting(tmp_path: Path) -> None:
    result = _inspect(tmp_path, "a.jpg", make_jpeg(trailing=b"junk"), strict=False)
    assert result.ok is True
    assert "trailing_data_removed" in result.warnings


def test_scanner_rejects_disguised_executable_and_renamed_image(tmp_path: Path) -> None:
    (tmp_path / "good.png").write_bytes(make_png())
    (tmp_path / "virus.jpg").write_bytes(EXE_BYTES)
    (tmp_path / "renamed.jpg").write_bytes(make_png())
    (tmp_path / "virus.exe").write_bytes(EXE_BYTES)

    policy = ExtensionPolicy()
    result = FileScanner(policy, SignaturePolicy(policy, enabled=True)).scan(tmp_path)

    assert [entry.relative_path for entry in result.images] == ["good.png"]
    reasons = {Path(issue.path).name: issue.reason for issue in result.skipped}
    assert reasons == {
        "virus.jpg": "unrecognized_content",
        "renamed.jpg": "extension_mismatch:content_is_png",
        "virus.exe": "blocked_extension",
    }


# ----------------------------------------------------------- metadata removal

def test_jpeg_metadata_removed_but_orientation_kept() -> None:
    original = make_jpeg(exif=make_exif(orientation=6), comment=b"taken at home", trailing=b"extra")
    cleaned = sanitize_jpeg(original)

    assert b"GPS" not in cleaned
    assert b"taken at home" not in cleaned
    assert b"extra" not in cleaned
    assert cleaned.endswith(b"\xff\xd9")
    assert parse_jpeg(cleaned).has_metadata is False
    # The orientation-only EXIF block survives so photos are not shown sideways.
    assert b"Exif\x00\x00MM\x00*" in cleaned
    assert sanitize_jpeg(cleaned) == cleaned


def test_mp3_tags_removed() -> None:
    cleaned = sanitize_mp3(make_mp3(id3=b"TIT2\x00\x00\x00\x07\x00\x00\x00Secret"))
    assert cleaned == make_mp3()


def test_png_text_metadata_removed() -> None:
    cleaned = sanitize_png(make_png(text=b"Author\x00someone", trailing=b"tail"))
    assert cleaned == make_png()


# ------------------------------------------------------------- path & network

@pytest.mark.parametrize(
    "bad_path",
    [
        "../escape.jpg",
        "a/../../escape.jpg",
        "/etc/passwd.jpg",
        "C:/Windows/evil.jpg",
        "photo.jpg:payload.exe",
        "CON.jpg",
        "dir/aux.png",
        "photo.jpg.",
        "photo.jpg ",
        "a//b.jpg",
        "bad\x01name.jpg",
    ],
)
def test_path_validator_rejects_unsafe_paths(tmp_path: Path, bad_path: str) -> None:
    with pytest.raises(ValueError):
        PathSecurityValidator(tmp_path).validate_for_destination(bad_path)


def test_path_validator_accepts_normal_nested_path(tmp_path: Path) -> None:
    result = PathSecurityValidator(tmp_path).validate_for_destination("Trip 2024/day 1/photo.jpg")
    assert result == tmp_path.resolve() / "Trip 2024" / "day 1" / "photo.jpg"


def test_peer_allow_list_only_accepts_lan() -> None:
    peers = PeerAllowList()
    assert peers.is_allowed("192.168.1.20")
    assert peers.is_allowed("169.254.10.2")
    assert peers.is_allowed("127.0.0.1")
    assert not peers.is_allowed("8.8.8.8")
    assert not peers.is_allowed("not-an-ip")


def test_sender_refuses_public_receiver_address() -> None:
    with pytest.raises(NetworkPolicyError):
        resolve_lan_address("8.8.8.8", 5001, allow_remote=False)


# ------------------------------------------------------------ end to end

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _manifest(source_root: Path, *names: str) -> TransferManifest:
    policy = ExtensionPolicy()
    entries = [
        FileManifestEntry(
            relative_path=name,
            category=policy.allowed_category_for_extension(Path(name).suffix) or "images",
            extension=Path(name).suffix,
            size_bytes=(source_root / name).stat().st_size,
            modified_time_ns=0,
        )
        for name in names
    ]
    return TransferManifest(session_id="s", source_root=str(source_root), selected_categories=["images", "videos"], files=entries)


@pytest.fixture()
def receiver(tmp_path: Path):
    destination = tmp_path / "dest"
    events: list[str] = []
    service = ReceiverService(
        bind_host="127.0.0.1",
        port=_free_port(),
        destination_root=destination,
        pairing_code=PAIRING_CODE,
        chunk_size=4096,
        on_event=events.append,
    )
    service.start()
    service.events = events
    yield service
    service.stop()


class _UncheckedSender(SenderService):
    """A tampered sender that skips every local check, to prove the receiver
    enforces the rules on its own."""

    def _prepare_file(self, source_root, entry, staging_dir):
        return source_root / entry.relative_path


def test_receiver_blocks_files_even_from_a_tampered_sender(tmp_path: Path, receiver: ReceiverService) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "good.png").write_bytes(make_png(text=b"Author\x00someone"))
    (source / "virus.jpg").write_bytes(EXE_BYTES)
    (source / "renamed.jpg").write_bytes(make_png())
    (source / "polyglot.png").write_bytes(make_png(trailing=EXE_BYTES))
    (source / "payload.exe").write_bytes(EXE_BYTES)

    sender = _UncheckedSender(receiver_host="127.0.0.1", receiver_port=receiver.port, pairing_code=PAIRING_CODE, chunk_size=4096)
    results = sender.send_manifest(
        _manifest(source, "good.png", "virus.jpg", "renamed.jpg", "polyglot.png", "payload.exe"), source
    )

    statuses = {item.relative_path: (item.status, item.reason) for item in results}
    assert statuses["good.png"] == ("sent", "")
    assert statuses["virus.jpg"] == ("rejected", "receiver: suspicious_content:windows_executable")
    assert statuses["renamed.jpg"] == ("rejected", "receiver: extension_mismatch:content_is_png")
    assert statuses["polyglot.png"][0] == "rejected"
    assert statuses["payload.exe"] == ("skipped", "extension_not_allowed:.exe")

    dest = receiver.destination_root
    assert sorted(path.name for path in dest.iterdir()) == ["good.png"]
    # The receiver strips metadata itself as well.
    assert (dest / "good.png").read_bytes() == make_png()


def test_normal_sender_strips_metadata_and_refuses_bad_files(tmp_path: Path, receiver: ReceiverService) -> None:
    source = tmp_path / "src"
    (source / "album").mkdir(parents=True)
    (source / "album" / "photo.jpg").write_bytes(make_jpeg(exif=make_exif(), comment=b"secret note"))
    (source / "fake.png").write_bytes(EXE_BYTES)

    sender = SenderService(receiver_host="127.0.0.1", receiver_port=receiver.port, pairing_code=PAIRING_CODE, chunk_size=4096)
    results = sender.send_manifest(_manifest(source, "album/photo.jpg", "fake.png"), source)

    assert [item.status for item in results] == ["sent", "rejected"]
    assert "unrecognized_content" in results[1].reason
    received = (receiver.destination_root / "album" / "photo.jpg").read_bytes()
    assert b"GPS" not in received and b"secret note" not in received
    assert not (receiver.destination_root / "fake.png").exists()


def test_pdf_and_mp3_transfer_end_to_end(tmp_path: Path, receiver: ReceiverService) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "doc.pdf").write_bytes(make_pdf())
    (source / "song.mp3").write_bytes(make_mp3(id3=b"TIT2\x00\x00\x00\x07\x00\x00\x00Secret"))
    (source / "bad.pdf").write_bytes(make_pdf(extra_objects=b"5 0 obj << /OpenAction << /S /JavaScript >> >> endobj\n"))

    sender = _UncheckedSender(receiver_host="127.0.0.1", receiver_port=receiver.port, pairing_code=PAIRING_CODE)
    results = sender.send_manifest(_manifest(source, "doc.pdf", "song.mp3", "bad.pdf"), source)

    statuses = {item.relative_path: (item.status, item.reason) for item in results}
    assert statuses["doc.pdf"] == ("sent", "")
    assert statuses["song.mp3"] == ("sent", "")
    assert statuses["bad.pdf"] == ("rejected", "receiver: pdf_active_content:JavaScript")
    dest = receiver.destination_root
    assert sorted(path.name for path in dest.iterdir()) == ["doc.pdf", "song.mp3"]
    # The receiver strips the tags itself even when a tampered sender did not.
    assert (dest / "song.mp3").read_bytes() == make_mp3()


def test_wrong_pairing_code_is_refused(tmp_path: Path, receiver: ReceiverService) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.png").write_bytes(make_png())

    sender = SenderService(receiver_host="127.0.0.1", receiver_port=receiver.port, pairing_code="wrong-code-123")
    with pytest.raises(AuthError):
        sender.send_manifest(_manifest(source, "a.png"), source)
    assert list(receiver.destination_root.iterdir()) == []
    assert any("wrong pairing code" in event for event in receiver.events)


def test_pairing_code_too_short() -> None:
    with pytest.raises(AuthError):
        SenderService(receiver_host="127.0.0.1", receiver_port=1, pairing_code="short")
    with pytest.raises(AuthError):
        SenderService(receiver_host="127.0.0.1", receiver_port=1, pairing_code="11-chars-ab")


def test_guessing_from_many_addresses_locks_out_everyone(receiver: ReceiverService) -> None:
    for host in range(1, 16):
        receiver._record_auth_failure(f"192.168.1.{host}")
    assert receiver._is_locked_out("192.168.1.200")


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_received_file_is_not_executable(tmp_path: Path, receiver: ReceiverService) -> None:
    source = tmp_path / "src"
    source.mkdir()
    photo = source / "a.png"
    photo.write_bytes(make_png())
    photo.chmod(0o755)

    sender = SenderService(receiver_host="127.0.0.1", receiver_port=receiver.port, pairing_code=PAIRING_CODE)
    assert [r.status for r in sender.send_manifest(_manifest(source, "a.png"), source)] == ["sent"]
    assert (receiver.destination_root / "a.png").stat().st_mode & 0o777 == 0o644


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_real_video_metadata_removed_with_ffmpeg(tmp_path: Path, receiver: ReceiverService) -> None:
    source = tmp_path / "src"
    source.mkdir()
    video = source / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5",
            "-metadata", "title=SECRET-TITLE", "-metadata", "location=+27.7172+085.3240/",
            "-c:v", "mpeg4", str(video),
        ],
        check=True,
    )
    assert b"SECRET-TITLE" in video.read_bytes()

    sender = SenderService(receiver_host="127.0.0.1", receiver_port=receiver.port, pairing_code=PAIRING_CODE)
    results = sender.send_manifest(_manifest(source, "clip.mp4"), source)

    assert [item.status for item in results] == ["sent"], results
    received = (receiver.destination_root / "clip.mp4").read_bytes()
    assert b"SECRET-TITLE" not in received
    assert b"+27.7172" not in received
