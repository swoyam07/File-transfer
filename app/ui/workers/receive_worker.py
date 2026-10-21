from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.models.transfer import AppConfig
from app.transfer.receiver_service import ReceiverService
from app.validation.extension_policy import ExtensionPolicy


class ReceiveWorker(QObject):
    started_signal = Signal()
    stopped_signal = Signal()
    failed = Signal(str)
    event = Signal(str)

    def __init__(
        self,
        *,
        bind_host: str,
        port: int,
        destination_root: str,
        pairing_code: str,
        config: AppConfig,
        extension_policy: ExtensionPolicy,
    ) -> None:
        super().__init__()
        self.bind_host = bind_host
        self.port = port
        self.destination_root = destination_root
        self.pairing_code = pairing_code
        self.config = config
        self.extension_policy = extension_policy
        self._service: ReceiverService | None = None

    @Slot()
    def start_listening(self) -> None:
        try:
            self._service = ReceiverService(
                bind_host=self.bind_host,
                port=self.port,
                destination_root=Path(self.destination_root),
                pairing_code=self.pairing_code,
                chunk_size=self.config.transfer.chunk_size_bytes,
                duplicate_policy=self.config.transfer.duplicate_policy,
                extension_policy=self.extension_policy,
                allowed_networks=self.config.security.allowed_sender_networks,
                max_file_size=self.config.transfer.max_file_size_bytes,
                max_file_count=self.config.transfer.max_file_count,
                strip_image_metadata=self.config.metadata.strip,
                on_event=self.event.emit,
            )
            self._service.start()
            self.started_signal.emit()
        except Exception as exc:
            self._service = None
            self.failed.emit(str(exc))

    @Slot()
    def stop_listening(self) -> None:
        try:
            if self._service is not None:
                self._service.stop()
                self._service = None
            self.stopped_signal.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
