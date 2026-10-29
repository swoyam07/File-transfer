from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.scanning.scanner import FileScanner
from app.transfer.rejected_files import RejectedFiles, is_unlisted_extension
from app.validation.extension_policy import ExtensionPolicy
from app.validation.signature_policy import SignaturePolicy


class ScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)
    scan_progress = Signal(int, int)  # done, total

    def __init__(
        self,
        source_root: str,
        extension_policy: ExtensionPolicy,
        rejected: RejectedFiles | None = None,
    ) -> None:
        super().__init__()
        self.source_root = source_root
        self.extension_policy = extension_policy
        self.rejected = rejected
        self._last_percent: int | None = None

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit("Starting scan (checking the real content of every file)...")
            scanner = FileScanner(
                extension_policy=self.extension_policy,
                signature_policy=SignaturePolicy(self.extension_policy, enabled=True),
            )
            result = scanner.scan(
                Path(self.source_root),
                exclude=self.rejected.folder if self.rejected else None,
                on_progress=self._report_progress,
            )
            if self.rejected is not None:
                move_rejected(self.rejected, [
                    (Path(issue.path).relative_to(result.source_root).as_posix(), issue.reason)
                    for issue in result.skipped
                    if is_unlisted_extension(issue.reason)
                ], self.progress.emit)
            self.progress.emit("Scan completed.")
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _report_progress(self, done: int, total: int) -> None:
        # One signal per whole percent, so a big folder does not flood the GUI thread.
        percent = done * 100 // total if total else 100
        if percent != self._last_percent:
            self._last_percent = percent
            self.scan_progress.emit(done, total)


def move_rejected(rejected: RejectedFiles, files: list[tuple[str, str]], report) -> None:
    moved = 0
    for relative_path, reason in files:
        try:
            if rejected.move(relative_path, reason) is not None:
                moved += 1
        except OSError as exc:
            report(f"Could not move {relative_path} to the rejected folder: {exc}")
    if moved:
        report(f"Moved {moved} rejected file(s) to {rejected.folder} (see reasons.csv)")
