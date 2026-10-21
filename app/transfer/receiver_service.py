from __future__ import annotations

import hashlib
import logging
import os
import shutil
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.constants import MAX_CHUNK_SIZE, MAX_FILE_COUNT, MAX_MANIFEST_BYTES, WIRE_PROTOCOL_VERSION
from app.exceptions import ProtocolError
from app.models.resume import ResumeState
from app.networking.transport import SocketTransport
from app.security import auth
from app.security.network_policy import DEFAULT_ALLOWED_NETWORKS, PeerAllowList
from app.security.path_validator import PathSecurityValidator
from app.state.resume_store import ResumeStore
from app.transfer.duplicate_policy import resolve_duplicate_path
from app.utils.time_utils import utc_now_iso
from app.validation.content_scanner import ContentScanner
from app.validation.extension_policy import ExtensionPolicy
from app.validation.media_inspector import MediaInspector, sanitize_image_bytes

logger = logging.getLogger(__name__)

# How long the receiver waits for the next message from the sender. Must cover
# the sender removing metadata from a large video before FILE_START.
_READ_TIMEOUT_SECONDS = 30 * 60.0
_HANDSHAKE_TIMEOUT_SECONDS = 15.0
_MIN_CHUNK_SIZE = 4096
_DISK_SPACE_MARGIN = 256 * 1024 * 1024
_MAX_AUTH_FAILURES = 5
_AUTH_LOCKOUT_SECONDS = 300.0
_DEFAULT_MAX_FILE_SIZE = 1024 ** 4


class FileRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ReceiverService:
    """
    Accepts files from an authenticated sender and independently re-checks
    every one of them. Nothing the sender says is trusted: extension, size,
    path and content are all validated here, and a file only appears in the
    destination folder after it passes.
    """

    def __init__(
        self,
        *,
        bind_host: str,
        port: int,
        destination_root: Path,
        pairing_code: str,
        chunk_size: int = 1024 * 1024,
        duplicate_policy: str = "skip",
        extension_policy: ExtensionPolicy | None = None,
        allowed_networks: list[str] | tuple[str, ...] = DEFAULT_ALLOWED_NETWORKS,
        max_file_size: int = _DEFAULT_MAX_FILE_SIZE,
        max_file_count: int = MAX_FILE_COUNT,
        strip_image_metadata: bool = True,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        self.bind_host = bind_host
        self.port = port
        self.destination_root = destination_root.resolve()
        self.chunk_size = chunk_size
        self.duplicate_policy = "skip" if duplicate_policy == "skip_identical" else duplicate_policy
        self.max_file_size = max_file_size
        self.max_file_count = max_file_count
        self.strip_image_metadata = strip_image_metadata
        self.resume_store = ResumeStore()
        self._key = auth.derive_key(pairing_code)
        self._extension_policy = extension_policy or ExtensionPolicy()
        self._inspector = MediaInspector(strict=True)
        self._peers = PeerAllowList(allowed_networks)
        self._auth_failures: dict[str, tuple[int, float]] = {}
        self._on_event = on_event or (lambda message: None)
        self.destination_root.mkdir(parents=True, exist_ok=True)
        self._path_validator = PathSecurityValidator(self.destination_root)
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._server_socket: socket.socket | None = None
        self._bind_error: Exception | None = None
        logger.info(f"ReceiverService initialized with destination: {self.destination_root}")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self._ready_event.wait(timeout=5)
        if self._bind_error is not None:
            raise self._bind_error

    def stop(self) -> None:
        self._stop_event.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _event(self, message: str) -> None:
        logger.info(message)
        self._on_event(message)

    def _serve(self) -> None:
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.bind_host, self.port))
            server.listen(1)
        except OSError as exc:
            self._bind_error = exc
            self._ready_event.set()
            return

        with server:
            self._server_socket = server
            self._ready_event.set()

            while not self._stop_event.is_set():
                try:
                    server.settimeout(0.5)
                    conn, addr = server.accept()
                except TimeoutError:
                    continue
                except OSError:
                    break

                peer_ip = addr[0]
                with conn:
                    if not self._peers.is_allowed(peer_ip):
                        self._event(f"Refused connection from {peer_ip}: not an allowed LAN address")
                        continue
                    if self._is_locked_out(peer_ip):
                        self._event(f"Refused connection from {peer_ip}: too many wrong pairing codes")
                        continue

                    conn.settimeout(_HANDSHAKE_TIMEOUT_SECONDS)
                    conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
                    transport = SocketTransport(conn)
                    try:
                        self._handle_connection(transport, peer_ip)
                    except (ProtocolError, auth.AuthError, ValueError, KeyError, TypeError, OSError) as exc:
                        self._event(f"Connection from {peer_ip} closed: {exc}")
                    except Exception as exc:
                        logger.exception("receiver_unexpected_error")
                        self._event(f"Connection from {peer_ip} failed: {exc}")

    # ------------------------------------------------------------- handshake

    def _is_locked_out(self, peer_ip: str) -> bool:
        failures, last = self._auth_failures.get(peer_ip, (0, 0.0))
        if failures >= _MAX_AUTH_FAILURES and time.monotonic() - last < _AUTH_LOCKOUT_SECONDS:
            return True
        return False

    def _record_auth_failure(self, peer_ip: str) -> None:
        failures, last = self._auth_failures.get(peer_ip, (0, 0.0))
        if time.monotonic() - last >= _AUTH_LOCKOUT_SECONDS:
            failures = 0
        self._auth_failures[peer_ip] = (failures + 1, time.monotonic())

    def _authenticate(self, transport: SocketTransport, peer_ip: str) -> bytes | None:
        hello = transport.receive_json_message()
        if hello.get("type") != "HELLO":
            transport.send_json_message({"type": "ERROR", "reason": "expected_hello"})
            return None
        if hello.get("protocol_version") != WIRE_PROTOCOL_VERSION:
            transport.send_json_message({"type": "ERROR", "reason": "protocol_version_mismatch"})
            self._event(f"Refused {peer_ip}: sender uses a different protocol version")
            return None
        client_nonce = auth.check_nonce(hello.get("client_nonce"))
        server_nonce = auth.new_nonce()
        transport.send_json_message({
            "type": "HELLO_ACK",
            "protocol_version": WIRE_PROTOCOL_VERSION,
            "server_nonce": server_nonce,
        })

        request = transport.receive_json_message()
        expected = auth.client_proof(self._key, client_nonce, server_nonce)
        if request.get("type") != "AUTH_REQUEST" or not auth.verify(expected, request.get("proof")):
            self._record_auth_failure(peer_ip)
            time.sleep(1.0)  # slow down guessing
            transport.send_json_message({"type": "AUTH_RESULT", "ok": False})
            self._event(f"Refused {peer_ip}: wrong pairing code")
            return None

        self._auth_failures.pop(peer_ip, None)
        transport.send_json_message({
            "type": "AUTH_RESULT",
            "ok": True,
            "proof": auth.server_proof(self._key, client_nonce, server_nonce),
        })
        return auth.session_key(self._key, client_nonce, server_nonce)

    # -------------------------------------------------------------- session

    def _handle_connection(self, transport: SocketTransport, peer_ip: str) -> None:
        session = self._authenticate(transport, peer_ip)
        if session is None:
            return
        transport.set_timeouts(read_timeout=_READ_TIMEOUT_SECONDS, write_timeout=None)
        self._event(f"Sender {peer_ip} authenticated")

        manifest_message = transport.receive_json_message(max_bytes=MAX_MANIFEST_BYTES)
        if manifest_message.get("type") != "MANIFEST":
            transport.send_json_message({"type": "ERROR", "reason": "expected_manifest"})
            return

        try:
            files = self._validate_manifest(manifest_message)
        except FileRejected as exc:
            transport.send_json_message({"type": "MANIFEST_RESULT", "accepted": False, "reason": exc.reason})
            self._event(f"Manifest rejected: {exc.reason}")
            return

        session_id = str(manifest_message.get("session_id", ""))[:128]
        transport.send_json_message({"type": "MANIFEST_RESULT", "accepted": True, "file_count": len(files)})
        self._event(f"Transfer started: {len(files)} file(s)")

        received = rejected = 0
        for item in files:
            outcome = self._receive_one_file(transport, session, session_id, item)
            if outcome == "received":
                received += 1
            elif outcome == "rejected":
                rejected += 1

        done = transport.receive_json_message()
        if done.get("type") == "TRANSFER_COMPLETE":
            transport.send_json_message({"type": "TRANSFER_COMPLETE_ACK"})
            self._event(f"Transfer complete: {received} received, {rejected} rejected")

    def _validate_manifest(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        files = message.get("files")
        if not isinstance(files, list):
            raise FileRejected("manifest_files_missing")
        if len(files) > self.max_file_count:
            raise FileRejected("too_many_files")

        seen: set[str] = set()
        total = 0
        for item in files:
            if not isinstance(item, dict):
                raise FileRejected("manifest_entry_invalid")
            path = item.get("relative_path")
            size = item.get("size_bytes")
            if not isinstance(path, str) or not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise FileRejected("manifest_entry_invalid")
            key = path.lower()
            if key in seen:
                raise FileRejected("manifest_duplicate_path")
            seen.add(key)
            total += size

        free = shutil.disk_usage(self.destination_root).free
        if total + _DISK_SPACE_MARGIN > free:
            raise FileRejected("not_enough_disk_space")
        return files

    # ----------------------------------------------------------------- files

    def _check_destination(self, relative_path: str) -> tuple[Path, str]:
        extension = Path(relative_path).suffix.lower()
        if not self._extension_policy.is_allowed(extension):
            raise FileRejected(f"extension_not_allowed:{extension or 'none'}")
        try:
            final_path = self._path_validator.validate_for_destination(relative_path)
        except ValueError as exc:
            raise FileRejected(f"invalid_file_path:{exc}") from exc
        return final_path, extension

    def _receive_one_file(
        self,
        transport: SocketTransport,
        session: bytes,
        session_id: str,
        item: dict[str, Any],
    ) -> str:
        relative_path = item["relative_path"]
        file_start = transport.receive_json_message()
        if file_start.get("type") == "FILE_CANCEL" and file_start.get("relative_path") == relative_path:
            self._event(f"Skipped by sender: {relative_path}")
            return "cancelled"
        if file_start.get("type") != "FILE_START" or file_start.get("relative_path") != relative_path:
            raise ProtocolError("expected_file_start_for_next_manifest_entry")

        size = file_start.get("size_bytes")
        chunk_size = file_start.get("chunk_size")
        try:
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                raise FileRejected("invalid_size")
            if size > self.max_file_size:
                raise FileRejected("file_too_large")
            if not isinstance(chunk_size, int) or not _MIN_CHUNK_SIZE <= chunk_size <= MAX_CHUNK_SIZE:
                raise FileRejected("invalid_chunk_size")
            final_path, extension = self._check_destination(relative_path)
        except FileRejected as exc:
            # The sender has not streamed anything yet, so a skip keeps both sides in sync.
            self._event(f"Rejected {relative_path}: {exc.reason}")
            transport.send_json_message({"type": "FILE_SKIP", "reason": exc.reason})
            return "rejected"

        final_path.parent.mkdir(parents=True, exist_ok=True)
        decision = resolve_duplicate_path(final_path, self.duplicate_policy)
        if decision.action in ("fail", "skip"):
            transport.send_json_message({"type": "FILE_SKIP", "reason": "duplicate_exists"})
            self._event(f"Skipped {relative_path}: already exists")
            return "skipped"

        target_path = decision.target_path
        part_path = self.resume_store.part_file_path_for(target_path)
        state_path = self.resume_store.state_file_path_for(target_path)
        offset = self._resume_offset(part_path, state_path, size)
        transport.send_json_message({"type": "FILE_RESUME_INFO", "offset": offset})

        digest = hashlib.sha256()
        scanner = ContentScanner()
        if offset:
            # Re-hash and re-scan what was received in an earlier session.
            with part_path.open("rb") as existing:
                while chunk := existing.read(8 * 1024 * 1024):
                    digest.update(chunk)
                    scanner.feed(chunk)

        started_at = utc_now_iso()
        with part_path.open("r+b" if offset else "wb") as handle:
            handle.seek(offset)
            handle.truncate()
            bytes_written = offset
            while bytes_written < size:
                chunk = transport.receive_exactly(min(chunk_size, size - bytes_written))
                handle.write(chunk)
                digest.update(chunk)
                scanner.feed(chunk)
                bytes_written += len(chunk)
                self.resume_store.save(state_path, ResumeState(
                    state_version=1,
                    session_id=session_id,
                    transfer_id=relative_path,
                    relative_path=relative_path,
                    original_filename=Path(relative_path).name,
                    expected_size=size,
                    bytes_written=bytes_written,
                    chunk_size=chunk_size,
                    source_size=size,
                    source_mtime_ns=0,
                    expected_sha256=None,
                    status="in_progress",
                    retry_count=0,
                    started_at=started_at,
                    updated_at=utc_now_iso(),
                ))
            handle.flush()
            os.fsync(handle.fileno())

        file_complete = transport.receive_json_message()
        if file_complete.get("type") != "FILE_COMPLETE" or file_complete.get("relative_path") != relative_path:
            raise ProtocolError("expected_file_complete")

        try:
            actual_sha256 = digest.hexdigest()
            claimed = file_complete.get("sha256")
            if not isinstance(claimed, str) or claimed.lower() != actual_sha256:
                raise FileRejected("hash_mismatch")
            expected_tag = auth.file_tag(session, relative_path, size, actual_sha256)
            if not auth.verify(expected_tag, file_complete.get("tag")):
                raise FileRejected("integrity_tag_invalid")
            if scanner.finding:
                raise FileRejected(f"suspicious_content:{scanner.finding}")
            self._verify_and_clean(part_path, extension)
        except FileRejected as exc:
            part_path.unlink(missing_ok=True)
            self.resume_store.delete(state_path)
            transport.send_json_message({"type": "FILE_RESULT", "ok": False, "reason": exc.reason})
            self._event(f"Rejected {relative_path}: {exc.reason}")
            return "rejected"

        if decision.action == "replace" and target_path.exists():
            target_path.unlink()
        part_path.replace(target_path)
        self.resume_store.delete(state_path)
        transport.send_json_message({"type": "FILE_RESULT", "ok": True, "sha256": actual_sha256})
        self._event(f"Received {relative_path} ({size} bytes)")
        return "received"

    def _resume_offset(self, part_path: Path, state_path: Path, size: int) -> int:
        if not (part_path.exists() and state_path.exists()):
            return 0
        try:
            consistency = self.resume_store.check_consistency(part_path, state_path)
            state = self.resume_store.load(state_path)
        except (OSError, ValueError, KeyError, TypeError):
            return 0
        if not consistency.is_consistent or state.expected_size != size:
            return 0
        return min(consistency.actual_part_size, size)

    def _verify_and_clean(self, part_path: Path, extension: str) -> None:
        result = self._inspector.inspect(part_path, claimed_extension=extension)
        if not result.ok:
            raise FileRejected(result.reason)
        if result.category != self._extension_policy.allowed_category_for_extension(extension):
            raise FileRejected("category_mismatch")
        if result.category == "images" and self.strip_image_metadata:
            cleaned = sanitize_image_bytes(part_path.read_bytes())
            if cleaned is not None:
                part_path.write_bytes(cleaned)
