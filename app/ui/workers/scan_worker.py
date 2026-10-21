from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.scanning.scanner import FileScanner
from app.validation.extension_policy import ExtensionPolicy
from app.validation.signature_policy import SignaturePolicy


class ScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, source_root: str, extension_policy: ExtensionPolicy) -> None:
        super().__init__()
        self.source_root = source_root
        self.extension_policy = extension_policy

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit("Starting scan (checking the real content of every file)...")
            scanner = FileScanner(
                extension_policy=self.extension_policy,
                signature_policy=SignaturePolicy(self.extension_policy, enabled=True),
            )
            result = scanner.scan(Path(self.source_root))
            self.progress.emit("Scan completed.")
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
