from __future__ import annotations

import socket
import time
from pathlib import Path

from app.models.manifest import FileManifestEntry, TransferManifest
from app.transfer.receiver_service import ReceiverService
from app.transfer.sender_service import SenderService
from tests.unit.media_samples import make_jpeg

PAIRING_CODE = "test-pairing-code"


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_transfer_localhost_single_file(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "dest"
    source_root.mkdir()
    destination_root.mkdir()

    source_file = source_root / "photo.jpg"
    source_bytes = make_jpeg()
    source_file.write_bytes(source_bytes)

    entry = FileManifestEntry(
        relative_path="photo.jpg",
        category="images",
        extension=".jpg",
        size_bytes=len(source_bytes),
        modified_time_ns=source_file.stat().st_mtime_ns,
    )
    manifest = TransferManifest(
        session_id="session-1",
        protocol_version=1,
        source_root=str(source_root),
        selected_categories=["images"],
        files=[entry],
    )

    port = get_free_port()
    receiver = ReceiverService(
        bind_host="127.0.0.1",
        port=port,
        destination_root=destination_root,
        chunk_size=4096,
        duplicate_policy="replace",
        pairing_code=PAIRING_CODE,
    )
    receiver.start()
    time.sleep(0.1)

    sender = SenderService(receiver_host="127.0.0.1", receiver_port=port, chunk_size=4096, pairing_code=PAIRING_CODE)
    results = sender.send_manifest(manifest, source_root)

    receiver.stop()

    received_file = destination_root / "photo.jpg"
    assert received_file.exists() is True
    assert received_file.read_bytes() == source_bytes
    assert [item.status for item in results] == ["sent"]


def test_sender_reports_progress_for_every_file(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "dest"
    source_root.mkdir()
    destination_root.mkdir()
    payloads = {"one.jpg": make_jpeg(comment=b"x" * 9000), "two.jpg": make_jpeg()}
    entries = []
    for name, data in payloads.items():
        (source_root / name).write_bytes(data)
        entries.append(FileManifestEntry(
            relative_path=name, category="images", extension=".jpg", size_bytes=len(data), modified_time_ns=0,
        ))
    manifest = TransferManifest(
        session_id="session-2", protocol_version=1, source_root=str(source_root),
        selected_categories=["images"], files=entries,
    )

    port = get_free_port()
    receiver = ReceiverService(
        bind_host="127.0.0.1", port=port, destination_root=destination_root,
        duplicate_policy="replace", pairing_code=PAIRING_CODE,
    )
    receiver.start()
    time.sleep(0.1)
    calls: list[tuple[int, int, int]] = []
    sender = SenderService(
        receiver_host="127.0.0.1", receiver_port=port, chunk_size=4096, pairing_code=PAIRING_CODE,
        strip_image_metadata=False,  # keep the 9 KB comment so the file spans several chunks
        file_progress=lambda number, done, size: calls.append((number, done, size)),
    )
    results = sender.send_manifest(manifest, source_root)
    receiver.stop()

    assert [item.status for item in results] == ["sent", "sent"]
    first = [call for call in calls if call[0] == 1]
    assert first[0] == (1, 0, 1) and first[-1] == (1, 1, 1)
    byte_calls = first[1:-1]
    assert len(byte_calls) > 1  # several 4 KB chunks, each reported
    assert [done for _, done, _ in byte_calls] == sorted(done for _, done, _ in byte_calls)
    assert byte_calls[-1][1] == byte_calls[-1][2]  # last chunk reaches the file size
    assert [call for call in calls if call[0] == 2][-1] == (2, 1, 1)
