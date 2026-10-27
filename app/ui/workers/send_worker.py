from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.models.manifest import TransferManifest
from app.models.transfer import AppConfig
from app.transfer.rejected_files import RejectedFiles, is_file_problem
from app.transfer.sender_service import SenderService
from app.ui.workers.scan_worker import move_rejected
from app.validation.extension_policy import ExtensionPolicy


class SendWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        *,
        receiver_host: str,
        receiver_port: int,
        pairing_code: str,
        manifest: TransferManifest,
        source_root: str,
        config: AppConfig,
        extension_policy: ExtensionPolicy,
        heavy_mode: bool = False,
        rejected: RejectedFiles | None = None,
    ) -> None:
        super().__init__()
        self.receiver_host = receiver_host
        self.receiver_port = receiver_port
        self.pairing_code = pairing_code
        self.manifest = manifest
        self.source_root = source_root
        self.config = config
        self.extension_policy = extension_policy
        self.heavy_mode = heavy_mode
        self.rejected = rejected

    @Slot()
    def run(self) -> None:
        try:
            mode_label = "heavy video" if self.heavy_mode else "standard"
            self.progress.emit(f"Connecting to receiver ({mode_label} mode)...")
            sender = SenderService(
                receiver_host=self.receiver_host,
                receiver_port=self.receiver_port,
                pairing_code=self.pairing_code,
                chunk_size=self.config.transfer.chunk_size_bytes,
                heavy_mode=self.heavy_mode,
                strip_image_metadata=self.config.metadata.strip,
                strip_video_metadata=self.config.metadata.strip,
                allow_remote=self.config.security.allow_remote_connections,
                extension_policy=self.extension_policy,
                connect_timeout=self.config.network.connect_timeout_seconds,
                temp_folder=self.config.storage.sender_temp_folder,
                progress=self.progress.emit,
            )
            results = sender.send_manifest(self.manifest, Path(self.source_root))
            if self.rejected is not None:
                move_rejected(self.rejected, [
                    (item.relative_path, item.reason)
                    for item in results
                    if item.status == "rejected" and is_file_problem(item.reason)
                ], self.progress.emit)
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))
