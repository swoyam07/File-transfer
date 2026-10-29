from __future__ import annotations

from itertools import accumulate
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
    # overall percent, file number, file count, file path, file percent
    transfer_progress = Signal(int, int, int, str, int)

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
        self.rejected = rejected
        # Overall progress weighs each file by its scanned size.
        self._sizes = [max(entry.size_bytes, 1) for entry in manifest.files]
        self._starts = list(accumulate(self._sizes, initial=0))
        self._last_progress: tuple[int, int, int] | None = None

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit("Connecting to receiver...")
            sender = SenderService(
                receiver_host=self.receiver_host,
                receiver_port=self.receiver_port,
                pairing_code=self.pairing_code,
                chunk_size=self.config.transfer.chunk_size_bytes,
                strip_image_metadata=self.config.metadata.strip,
                strip_video_metadata=self.config.metadata.strip,
                allow_remote=self.config.security.allow_remote_connections,
                extension_policy=self.extension_policy,
                connect_timeout=self.config.network.connect_timeout_seconds,
                temp_folder=self.config.storage.sender_temp_folder,
                progress=self.progress.emit,
                file_progress=self._report_progress,
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

    def _report_progress(self, number: int, done: int, size: int) -> None:
        fraction = min(done / size, 1.0) if size else 1.0
        index = number - 1
        overall = int((self._starts[index] + fraction * self._sizes[index]) * 100 / self._starts[-1])
        update = (overall, number, int(fraction * 100))
        if update != self._last_progress:  # only whole-percent changes reach the GUI
            self._last_progress = update
            self.transfer_progress.emit(
                overall, number, len(self._sizes), self.manifest.files[index].relative_path, update[2]
            )
