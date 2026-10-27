from __future__ import annotations

import socket
import time
from pathlib import Path

import pytest

from app.integrity.hashing import sha256_file
from app.models.manifest import FileManifestEntry, TransferManifest
from app.models.resume import ResumeState
from app.state.resume_store import ResumeStore
from app.transfer.receiver_service import ReceiverService
from app.transfer.sender_service import SenderService
from tests.unit.media_samples import make_mp4

PAIRING_CODE = "test-pairing-code"


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# The receiver saves a resume point every few hundred MB, so after a crash the
# part file usually holds more data than the last resume point records.
@pytest.mark.parametrize("unrecorded_tail", [b"", b"written after the last resume point" * 50])
def test_transfer_resumes_from_existing_partial_file(tmp_path: Path, unrecorded_tail: bytes) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "dest"
    source_root.mkdir()
    destination_root.mkdir()

    source_file = source_root / "video.mp4"
    source_bytes = make_mp4() + b"\x00\x00\x9c\x48mdat" + b"0123456789abcdef" * 2500
    source_file.write_bytes(source_bytes)

    partial_size = 20000
    final_path = destination_root / "video.mp4"
    resume_store = ResumeStore()
    part_path = resume_store.part_file_path_for(final_path)
    state_path = resume_store.state_file_path_for(final_path)

    part_path.write_bytes(source_bytes[:partial_size] + unrecorded_tail)
    resume_store.save(
        state_path,
        ResumeState(
            state_version=1,
            session_id="session-1",
            transfer_id="video.mp4",
            relative_path="video.mp4",
            original_filename="video.mp4",
            expected_size=len(source_bytes),
            bytes_written=partial_size,
            chunk_size=4096,
            source_size=len(source_bytes),
            source_mtime_ns=source_file.stat().st_mtime_ns,
            expected_sha256=sha256_file(source_file, chunk_size=4096),
            status="in_progress",
            retry_count=0,
            started_at="2026-07-24T00:00:00Z",
            updated_at="2026-07-24T00:00:00Z",
        ),
    )

    entry = FileManifestEntry(
        relative_path="video.mp4",
        category="videos",
        extension=".mp4",
        size_bytes=len(source_bytes),
        modified_time_ns=source_file.stat().st_mtime_ns,
    )
    manifest = TransferManifest(
        session_id="session-1",
        protocol_version=1,
        source_root=str(source_root),
        selected_categories=["videos"],
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

    sender = SenderService(
        receiver_host="127.0.0.1",
        receiver_port=port,
        chunk_size=4096,
        pairing_code=PAIRING_CODE,
        strip_video_metadata=False,
    )
    sender.send_manifest(manifest, source_root)

    receiver.stop()

    assert final_path.exists() is True
    assert final_path.read_bytes() == source_bytes
    assert state_path.exists() is False