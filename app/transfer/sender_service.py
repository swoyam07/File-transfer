from __future__ import annotations

import hashlib
import logging
import os
import shutil
import socket
import tempfile
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.constants import WIRE_PROTOCOL_VERSION
from app.exceptions import ProtocolError
from app.models.manifest import FileManifestEntry, TransferManifest
from app.networking.transport import SocketTransport
from app.security import auth
from app.security.network_policy import resolve_lan_address
from app.transfer.chunk_io import iter_file_chunks
from app.validation.extension_policy import ExtensionPolicy
from app.validation.media_inspector import sanitize_image_bytes, sanitize_mp3
from app.validation.signature_policy import SignaturePolicy
from app.validation.video_sanitizer import find_ffmpeg, strip_video_metadata

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 16 * 1024 * 1024
_READ_TIMEOUT_SECONDS = 120.0
# The receiver re-hashes and validates the whole file after the last chunk,
# which can take a while for very large videos.
_RESULT_TIMEOUT_SECONDS = 30 * 60.0
# Free space kept on the temp folder's drive beyond the cleaned copy itself.
_TEMP_SPACE_MARGIN = 512 * 1024 * 1024


@dataclass(slots=True)
class FileSendResult:
    relative_path: str
    status: str  # "sent", "skipped", "rejected"
    reason: str = ""


@dataclass(slots=True)
class _PreparedFile:
    entry: FileManifestEntry
    staging_dir: Path | None
    send_path: Path | None = None
    error: str = ""


class SenderService:
    def __init__(
        self,
        *,
        receiver_host: str,
        receiver_port: int,
        pairing_code: str,
        chunk_size: int = _CHUNK_SIZE,
        strip_image_metadata: bool = True,
        strip_video_metadata: bool = True,
        allow_remote: bool = False,
        extension_policy: ExtensionPolicy | None = None,
        connect_timeout: float = 10.0,
        temp_folder: Path | None = None,
        progress: Callable[[str], None] | None = None,
        file_progress: Callable[[int, int, int], None] | None = None,
    ) -> None:
        self.receiver_host = receiver_host
        self.receiver_port = receiver_port
        self.chunk_size = chunk_size
        self.strip_image_metadata = strip_image_metadata
        self.strip_video_metadata = strip_video_metadata
        self.allow_remote = allow_remote
        self.connect_timeout = connect_timeout
        self.temp_folder = temp_folder
        self._key = auth.derive_key(pairing_code)
        self._extension_policy = extension_policy or ExtensionPolicy()
        self._signature_policy = SignaturePolicy(self._extension_policy, enabled=True, strict=False)
        self._ffmpeg = find_ffmpeg() if strip_video_metadata else None
        self._progress = progress or (lambda message: None)
        # file_progress(file_number, bytes_done, file_size), file_number counting from 1.
        self._file_progress = file_progress or (lambda number, done, size: None)

    def send_manifest(self, manifest: TransferManifest, source_root: Path) -> list[FileSendResult]:
        source_root = source_root.resolve()
        address = resolve_lan_address(self.receiver_host, self.receiver_port, allow_remote=self.allow_remote)

        with socket.create_connection((address, self.receiver_port), timeout=self.connect_timeout) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            sock.settimeout(_READ_TIMEOUT_SECONDS)
            transport = SocketTransport(sock)

            session = self._authenticate(transport)

            transport.send_json_message({
                "type": "MANIFEST",
                "session_id": manifest.session_id,
                "protocol_version": WIRE_PROTOCOL_VERSION,
                "files": [self._entry_to_payload(entry) for entry in manifest.files],
            })
            manifest_result = transport.receive_json_message()
            if manifest_result.get("type") != "MANIFEST_RESULT" or not manifest_result.get("accepted"):
                raise RuntimeError(f"manifest_rejected: {manifest_result.get('reason', 'unknown')}")

            results: list[FileSendResult] = []
            files = manifest.files
            total = len(files)
            # The next file is checked and cleaned (ffmpeg for videos) while the
            # current one is on the wire, so the source drive, the network and
            # the receiver's drive all stay busy instead of taking turns.
            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="smt-prepare")
            upcoming: Future[_PreparedFile] | None = pool.submit(self._prepare, source_root, files[0]) if files else None
            try:
                for index, entry in enumerate(files, start=1):
                    assert upcoming is not None
                    prepared = upcoming.result()
                    upcoming = pool.submit(self._prepare, source_root, files[index]) if index < total else None
                    self._progress(f"[{index}/{total}] {entry.relative_path}")
                    self._file_progress(index, 0, 1)
                    try:
                        result = self._send_prepared(
                            transport, session, prepared, lambda done, size, number=index: self._file_progress(number, done, size)
                        )
                    finally:
                        _remove_staging(prepared)
                    self._file_progress(index, 1, 1)
                    results.append(result)
                    if result.status != "sent":
                        self._progress(f"    {result.status}: {result.reason}")
            finally:
                if upcoming is not None:  # the connection failed mid-batch
                    upcoming.add_done_callback(lambda future: _remove_staging(future.result()))
                pool.shutdown(wait=False)

            transport.send_json_message({"type": "TRANSFER_COMPLETE"})
            final_ack = transport.receive_json_message()
            if final_ack.get("type") != "TRANSFER_COMPLETE_ACK":
                raise RuntimeError("missing_transfer_complete_ack")
            return results

    def _authenticate(self, transport: SocketTransport) -> bytes:
        client_nonce = auth.new_nonce()
        transport.send_json_message({
            "type": "HELLO",
            "protocol_version": WIRE_PROTOCOL_VERSION,
            "client_nonce": client_nonce,
        })
        hello_ack = transport.receive_json_message()
        if hello_ack.get("type") != "HELLO_ACK":
            raise RuntimeError(f"receiver_refused_connection: {hello_ack.get('reason', 'unknown')}")
        if hello_ack.get("protocol_version") != WIRE_PROTOCOL_VERSION:
            raise RuntimeError("receiver_protocol_version_mismatch (update both computers)")
        server_nonce = auth.check_nonce(hello_ack.get("server_nonce"))

        transport.send_json_message({
            "type": "AUTH_REQUEST",
            "proof": auth.client_proof(self._key, client_nonce, server_nonce),
        })
        auth_result = transport.receive_json_message()
        if auth_result.get("type") != "AUTH_RESULT" or not auth_result.get("ok"):
            raise auth.AuthError("Pairing code rejected by receiver")
        if not auth.verify(auth.server_proof(self._key, client_nonce, server_nonce), auth_result.get("proof")):
            # The receiver does not know the pairing code: it is an impostor.
            raise auth.AuthError("Receiver failed to prove the pairing code")
        return auth.session_key(self._key, client_nonce, server_nonce)

    def _prepare(self, source_root: Path, entry: FileManifestEntry) -> _PreparedFile:
        """Runs on the prepare thread; never raises."""
        staging_dir = None
        try:
            staging_dir = Path(tempfile.mkdtemp(prefix="smt-send-", dir=self._temp_root(entry.size_bytes)))
            return _PreparedFile(entry, staging_dir, send_path=self._prepare_file(source_root, entry, staging_dir))
        except (ValueError, OSError, RuntimeError) as exc:
            return _PreparedFile(entry, staging_dir, error=str(exc))

    def _temp_root(self, size: int) -> str:
        """A folder with room for the cleaned copy of a file this size. On
        Fedora /tmp is kept in RAM and is too small for a long movie, so a
        folder on disk is preferred."""
        candidates = [str(self.temp_folder)] if self.temp_folder else []
        if os.name != "nt":
            candidates.append("/var/tmp")
        candidates.append(tempfile.gettempdir())
        for folder in candidates:
            try:
                if shutil.disk_usage(folder).free >= size + _TEMP_SPACE_MARGIN:
                    return folder
            except OSError:
                continue
        raise ValueError(f"not_enough_temp_space: needs {size + _TEMP_SPACE_MARGIN} bytes free in {candidates[0]}")

    def _send_prepared(
        self,
        transport: SocketTransport,
        session: bytes,
        prepared: _PreparedFile,
        report: Callable[[int, int], None],
    ) -> FileSendResult:
        entry = prepared.entry
        if prepared.send_path is None:
            logger.warning("file_not_sent", extra={"path": entry.relative_path, "reason": prepared.error})
            transport.send_json_message({"type": "FILE_CANCEL", "relative_path": entry.relative_path})
            return FileSendResult(entry.relative_path, "rejected", f"sender: {prepared.error}")
        return self._stream_file(transport, session, entry, prepared.send_path, report)

    def _prepare_file(self, source_root: Path, entry: FileManifestEntry, staging_dir: Path) -> Path:
        """Re-validate the file now (it may have changed since the scan) and
        return the path of a metadata-free copy to send."""
        source_path = source_root / Path(entry.relative_path)
        if source_path.is_symlink():
            raise ValueError("symlink_not_allowed")
        resolved = source_path.resolve()
        if not resolved.is_relative_to(source_root):
            raise ValueError("path_outside_source_folder")

        check = self._signature_policy.inspect_file(resolved, claimed_extension=entry.extension)
        if check.decision != "allow":
            raise ValueError(check.reason)

        category = self._extension_policy.allowed_category_for_extension(entry.extension)
        if category == "images" and self.strip_image_metadata:
            cleaned = sanitize_image_bytes(resolved.read_bytes())
            if cleaned is None:
                return resolved  # HEIC: validated, but no sanitizer
            staged = staging_dir / f"image{entry.extension}"
            staged.write_bytes(cleaned)
            return staged

        if category == "audio" and self.strip_image_metadata:
            staged = staging_dir / f"audio{entry.extension}"
            staged.write_bytes(sanitize_mp3(resolved.read_bytes()))
            return staged

        if category == "videos" and self.strip_video_metadata:
            if self._ffmpeg is None:
                logger.warning("ffmpeg_not_found_video_metadata_kept", extra={"path": entry.relative_path})
                return resolved
            staged = staging_dir / f"video{entry.extension}"
            self._progress(f"    removing video metadata: {entry.relative_path}")
            strip_video_metadata(resolved, staged, ffmpeg=self._ffmpeg)
            recheck = self._signature_policy.inspect_file(staged, claimed_extension=entry.extension)
            if recheck.decision != "allow":
                raise ValueError(f"sanitized_video_invalid: {recheck.reason}")
            return staged

        return resolved

    def _stream_file(
        self,
        transport: SocketTransport,
        session: bytes,
        entry: FileManifestEntry,
        send_path: Path,
        report: Callable[[int, int], None],
    ) -> FileSendResult:
        size = send_path.stat().st_size
        transport.send_json_message({
            "type": "FILE_START",
            "relative_path": entry.relative_path,
            "size_bytes": size,
            "chunk_size": self.chunk_size,
        })
        response = transport.receive_json_message()
        if response.get("type") == "FILE_SKIP":
            return FileSendResult(entry.relative_path, "skipped", str(response.get("reason", "")))
        if response.get("type") != "FILE_RESUME_INFO":
            raise ProtocolError(f"expected_file_resume_info, got: {response.get('type')}")
        offset = int(response["offset"])
        if offset < 0 or offset > size:
            raise ProtocolError("invalid_resume_offset")

        # Hash the whole file in one pass: bytes before the resume offset are
        # only hashed, the rest are hashed and sent.
        digest = hashlib.sha256()
        position = 0
        for chunk in iter_file_chunks(send_path, start_offset=0, chunk_size=self.chunk_size):
            digest.update(chunk)
            end = position + len(chunk)
            if end > offset:
                transport.send_all(chunk[max(offset - position, 0):])
            position = end
            report(position, size)
        if position != size:
            raise RuntimeError("file_changed_while_sending")

        sha256 = digest.hexdigest()
        transport.send_json_message({
            "type": "FILE_COMPLETE",
            "relative_path": entry.relative_path,
            "sha256": sha256,
            "tag": auth.file_tag(session, entry.relative_path, size, sha256),
        })
        transport.set_timeouts(read_timeout=_RESULT_TIMEOUT_SECONDS, write_timeout=None)
        try:
            result = transport.receive_json_message()
        finally:
            transport.set_timeouts(read_timeout=_READ_TIMEOUT_SECONDS, write_timeout=None)
        if result.get("type") != "FILE_RESULT":
            raise ProtocolError("expected_file_result")
        if not result.get("ok"):
            return FileSendResult(entry.relative_path, "rejected", f"receiver: {result.get('reason', 'unknown')}")
        return FileSendResult(entry.relative_path, "sent")

    def _entry_to_payload(self, entry: FileManifestEntry) -> dict[str, object]:
        # Timestamps and other source metadata are intentionally not sent.
        return {
            "relative_path": entry.relative_path,
            "category": entry.category,
            "extension": entry.extension,
            "size_bytes": entry.size_bytes,
        }


def _remove_staging(prepared: _PreparedFile) -> None:
    if prepared.staging_dir is not None:
        shutil.rmtree(prepared.staging_dir, ignore_errors=True)
