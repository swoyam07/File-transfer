from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.models.manifest import FileManifestEntry
from app.models.transfer import AppConfig
from app.security.auth import AuthError, validate_pairing_code
from app.transfer.rejected_files import RejectedFiles
from app.utils.size_utils import format_bytes
from app.scanning.manifest_builder import build_transfer_manifest
from app.ui.dialogs.settings_dialog import SettingsDialog
from app.ui.style import make_header, make_log_view, make_muted, make_primary, make_status_label, set_status
from app.ui.workers.scan_worker import ScanWorker
from app.ui.workers.send_worker import SendWorker
from app.validation.extension_policy import ExtensionPolicy


class SenderMainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.extension_policy = ExtensionPolicy.from_config(config.allowed_extensions, config.blocked_extensions)
        self.setWindowTitle("Safe Media Transfer - Sender")
        self.resize(880, 760)

        self._scan_result = None
        self._scan_thread: QThread | None = None
        self._scan_worker: ScanWorker | None = None
        self._send_thread: QThread | None = None
        self._send_worker: SendWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)

        self.receiver_ip_input = QLineEdit(config.network.receiver_ip)
        self.receiver_ip_input.setPlaceholderText("e.g. 192.168.50.2")
        self.port_input = QLineEdit(str(config.network.port))
        self.port_input.setMaximumWidth(90)
        self.pairing_input = QLineEdit(config.security.pairing_code)
        self.pairing_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pairing_input.setPlaceholderText("Same code as on the receiver (min. 12 characters)")
        self.source_folder_input = QLineEdit()
        self.source_folder_input.setPlaceholderText("Folder with the photos, videos, audio and PDFs to send")
        self.log_output = make_log_view()

        self.browse_button = QPushButton("Browse...")
        self.scan_button = make_primary(QPushButton("Scan"))

        self.transfer_images_button = QPushButton("Transfer Images")
        self.transfer_videos_button = QPushButton("Transfer Videos")
        self.transfer_audio_button = QPushButton("Transfer Audio")
        self.transfer_documents_button = QPushButton("Transfer PDFs")
        self.transfer_both_button = make_primary(QPushButton("Transfer All"))
        self.settings_button = QPushButton("Settings")

        self.scan_progress = QProgressBar()
        self.scan_progress.setFormat("Not scanned yet")
        self.scan_progress.setValue(0)
        self.send_progress = QProgressBar()
        self.send_progress.setFormat("Not sending")
        self.send_progress.setValue(0)

        self.status_label = make_status_label("Idle")
        self.summary_label = make_muted(QLabel("Run a scan to see what will be sent."))
        self.send_file_label = make_muted(QLabel(""))
        self._tiles: dict[str, tuple[QLabel, QLabel]] = {}

        connection_box = QGroupBox("Connection")
        receiver_row = QHBoxLayout()
        receiver_row.addWidget(self.receiver_ip_input)
        receiver_row.addWidget(QLabel("Port"))
        receiver_row.addWidget(self.port_input)
        connection_form = QFormLayout()
        connection_form.addRow("Receiver IP", receiver_row)
        connection_form.addRow("Pairing Code", self.pairing_input)
        connection_box.setLayout(connection_form)

        source_box = QGroupBox("Source")
        source_row = QHBoxLayout()
        source_row.addWidget(self.source_folder_input)
        source_row.addWidget(self.browse_button)
        source_row.addWidget(self.scan_button)
        source_box.setLayout(source_row)

        summary_box = QGroupBox("Scan Summary")
        tiles_row = QHBoxLayout()
        for category, label in (("images", "Images"), ("videos", "Videos"), ("audio", "Audio"), ("documents", "PDFs")):
            tiles_row.addWidget(self._make_tile(category, label))
        summary_layout = QVBoxLayout()
        summary_layout.addWidget(self.scan_progress)
        summary_layout.addLayout(tiles_row)
        summary_layout.addWidget(self.summary_label)
        summary_box.setLayout(summary_layout)

        transfer_box = QGroupBox("Transfer")
        transfer_row = QHBoxLayout()
        transfer_row.addWidget(self.transfer_images_button)
        transfer_row.addWidget(self.transfer_videos_button)
        transfer_row.addWidget(self.transfer_audio_button)
        transfer_row.addWidget(self.transfer_documents_button)
        transfer_row.addStretch()
        transfer_row.addWidget(self.transfer_both_button)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label)
        status_row.addWidget(self.send_progress, 1)
        transfer_layout = QVBoxLayout()
        transfer_layout.addLayout(transfer_row)
        transfer_layout.addLayout(status_row)
        transfer_layout.addWidget(self.send_file_label)
        transfer_box.setLayout(transfer_layout)

        log_box = QGroupBox("Log")
        log_layout = QVBoxLayout()
        log_layout.addWidget(self.log_output)
        log_box.setLayout(log_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 12, 16, 16)
        layout.addLayout(make_header("Safe Media Transfer", "Sender: send checked media to the receiver", self.settings_button))
        layout.addWidget(connection_box)
        layout.addWidget(source_box)
        layout.addWidget(summary_box)
        layout.addWidget(transfer_box)
        layout.addWidget(log_box, 1)

        central.setLayout(layout)
        self._refresh_transfer_buttons()

        self.browse_button.clicked.connect(self._choose_source_folder)
        self.scan_button.clicked.connect(self._start_scan)
        self.transfer_images_button.clicked.connect(lambda: self._start_transfer(["images"]))
        self.transfer_videos_button.clicked.connect(lambda: self._start_transfer(["videos"]))
        self.transfer_audio_button.clicked.connect(lambda: self._start_transfer(["audio"]))
        self.transfer_documents_button.clicked.connect(lambda: self._start_transfer(["documents"]))
        self.transfer_both_button.clicked.connect(
            lambda: self._start_transfer(["images", "videos", "audio", "documents"])
        )
        self.settings_button.clicked.connect(self._open_settings)

    def _make_tile(self, category: str, label: str) -> QFrame:
        count_label = QLabel("–")
        count_label.setStyleSheet("font-size: 16pt; font-weight: 600;")
        size_label = make_muted(QLabel(label))
        tile = QFrame()
        tile.setObjectName("tile")
        tile_layout = QVBoxLayout(tile)
        tile_layout.setSpacing(2)
        for widget in (count_label, size_label):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile_layout.addWidget(widget)
        self._tiles[category] = (count_label, size_label)
        return tile

    def _choose_source_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if folder:
            self.source_folder_input.setText(folder)

    def _start_scan(self) -> None:
        source_folder = self.source_folder_input.text().strip()
        if not source_folder:
            QMessageBox.warning(self, "Missing folder", "Select a source folder first.")
            return

        if self._scan_thread is not None and self._scan_thread.isRunning():
            self._append_log("Scan already in progress.")
            return

        self._append_log("Starting scan...")
        set_status(self.status_label, "Scanning...", "busy")
        self.scan_progress.setRange(0, 0)  # animated until the file list is ready
        self.scan_progress.setFormat("Listing files...")
        self.scan_button.setEnabled(False)

        self._scan_thread = QThread(self)
        self._scan_worker = ScanWorker(source_folder, self.extension_policy, self._rejected_files(source_folder))
        self._scan_worker.moveToThread(self._scan_thread)

        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.progress.connect(self._append_log)
        self._scan_worker.scan_progress.connect(self._on_scan_progress)
        self._scan_worker.finished.connect(self._handle_scan_finished)
        self._scan_worker.failed.connect(self._handle_worker_error)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.failed.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._on_scan_thread_finished)

        self._scan_thread.start()

    def _on_scan_progress(self, done: int, total: int) -> None:
        self.scan_progress.setRange(0, max(total, 1))
        self.scan_progress.setValue(done)
        self.scan_progress.setFormat(f"Scanned %p%  ({done:,} of {total:,} items)")

    def _on_scan_thread_finished(self) -> None:
        self.scan_button.setEnabled(True)
        if self._scan_worker is not None:
            self._scan_worker.deleteLater()
            self._scan_worker = None
        if self._scan_thread is not None:
            self._scan_thread.deleteLater()
            self._scan_thread = None

    def _handle_scan_finished(self, result) -> None:
        self._scan_result = result
        skipped_count = len(result.skipped)
        warning_count = len(result.warnings)

        labels = {"images": "Images", "videos": "Videos", "audio": "Audio", "documents": "PDFs"}
        for category, (count_label, size_label) in self._tiles.items():
            entries = result.category_entries(category)
            count_label.setText(f"{len(entries):,}")
            size_label.setText(f"{labels[category]} · {format_bytes(sum(item.size_bytes for item in entries))}")
        self.summary_label.setText(f"Skipped: {skipped_count}   ·   Warnings: {warning_count}")
        set_status(self.status_label, "Scan complete", "ok")
        self.scan_progress.setRange(0, 100)
        self.scan_progress.setValue(100)
        self.scan_progress.setFormat("Scan complete  (100%)")
        self._refresh_transfer_buttons()
        for issue in result.skipped:
            if issue.reason != "unsupported_extension":
                self._append_log(f"Blocked: {issue.path} ({issue.reason})")
        for issue in result.warnings:
            self._append_log(f"Note: {issue.path} ({issue.reason})")
        self._append_log("Scan completed.")

    def _start_transfer(self, categories: list[str]) -> None:
        if self._scan_result is None:
            QMessageBox.warning(self, "No scan", "Run a scan before transfer.")
            return

        source_root = self.source_folder_input.text().strip()
        receiver_ip = self.receiver_ip_input.text().strip()
        port_text = self.port_input.text().strip()

        if not source_root or not receiver_ip or not port_text:
            QMessageBox.warning(self, "Missing values", "Receiver IP, port, and source folder are required.")
            return
        try:
            pairing_code = validate_pairing_code(self.pairing_input.text())
            port = int(port_text)
        except (AuthError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid values", str(exc))
            return

        entries: list[FileManifestEntry] = []
        for category in categories:
            entries.extend(self._scan_result.category_entries(category))

        if not entries:
            QMessageBox.warning(self, "Nothing to send", "No files found in the selected categories.")
            return

        manifest = build_transfer_manifest(
            session_id=str(uuid.uuid4()),
            source_root=source_root,
            selected_categories=categories,
            entries=entries,
        )

        self._append_log(f"Starting transfer ({len(entries)} file(s))...")
        set_status(self.status_label, "Transferring...", "busy")
        self.send_progress.setRange(0, 0)  # animated while connecting
        self.send_progress.setFormat("Connecting...")
        self.send_file_label.setText("")
        self._refresh_transfer_buttons(busy=True)

        self._send_thread = QThread(self)
        self._send_worker = SendWorker(
            receiver_host=receiver_ip,
            receiver_port=port,
            pairing_code=pairing_code,
            manifest=manifest,
            source_root=source_root,
            config=self.config,
            extension_policy=self.extension_policy,
            rejected=self._rejected_files(source_root),
        )
        self._send_worker.moveToThread(self._send_thread)

        self._send_thread.started.connect(self._send_worker.run)
        self._send_worker.progress.connect(self._append_log)
        self._send_worker.transfer_progress.connect(self._on_transfer_progress)
        self._send_worker.finished.connect(self._handle_send_finished)
        self._send_worker.failed.connect(self._handle_worker_error)
        self._send_worker.finished.connect(self._send_thread.quit)
        self._send_worker.failed.connect(self._send_thread.quit)
        self._send_thread.finished.connect(self._on_send_thread_finished)

        self._send_thread.start()

    def _on_transfer_progress(self, overall: int, number: int, count: int, path: str, file_percent: int) -> None:
        self.send_progress.setRange(0, 100)
        self.send_progress.setValue(overall)
        self.send_progress.setFormat(f"Sent %p%  (file {number:,} of {count:,})")
        # At 100% the receiver re-hashes and checks the whole file before it answers.
        stage = "receiver is checking it" if file_percent >= 100 else f"{file_percent}%"
        self.send_file_label.setText(f"{path}  ·  {stage}")

    def _on_send_thread_finished(self) -> None:
        self._refresh_transfer_buttons()
        if self._send_worker is not None:
            self._send_worker.deleteLater()
            self._send_worker = None
        if self._send_thread is not None:
            self._send_thread.deleteLater()
            self._send_thread = None

    def _rejected_files(self, source_folder: str) -> RejectedFiles | None:
        if not self.config.transfer.move_rejected_files:
            return None
        return RejectedFiles(Path(source_folder), self.config.storage.rejected_folder)

    def _refresh_transfer_buttons(self, busy: bool = False) -> None:
        # A button is only clickable when the last scan found files of its type.
        def has(category: str) -> bool:
            return not busy and self._scan_result is not None and bool(self._scan_result.category_entries(category))

        self.transfer_images_button.setEnabled(has("images"))
        self.transfer_videos_button.setEnabled(has("videos"))
        self.transfer_audio_button.setEnabled(has("audio"))
        self.transfer_documents_button.setEnabled(has("documents"))
        self.transfer_both_button.setEnabled(any(has(c) for c in ("images", "videos", "audio", "documents")))

    def _handle_send_finished(self, results) -> None:
        sent = sum(1 for item in results if item.status == "sent")
        problems = [item for item in results if item.status != "sent"]
        set_status(self.status_label, f"Transfer complete: {sent} sent, {len(problems)} not sent", "warn" if problems else "ok")
        self.send_progress.setRange(0, 100)
        self.send_progress.setValue(100)
        self.send_progress.setFormat("Done  (100%)")
        self.send_file_label.setText("")
        for item in problems:
            self._append_log(f"Not sent ({item.status}): {item.relative_path} - {item.reason}")
        self._append_log(f"Transfer completed: {sent} of {len(results)} file(s) sent.")

    def _handle_worker_error(self, message: str) -> None:
        set_status(self.status_label, "Error", "error")
        for bar in (self.scan_progress, self.send_progress):
            if bar.maximum() == 0:  # stop an animated bar
                bar.setRange(0, 100)
                bar.setFormat("Stopped")
        self._append_log(f"Error: {message}")
        QMessageBox.critical(self, "Worker error", message)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec()

    def _append_log(self, message: str) -> None:
        self.log_output.append(message)