from __future__ import annotations

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.models.transfer import AppConfig
from app.security.auth import AuthError, validate_pairing_code
from app.ui.dialogs.settings_dialog import SettingsDialog
from app.ui.style import make_header, make_log_view, make_primary, make_status_label, set_status
from app.ui.workers.receive_worker import ReceiveWorker
from app.validation.extension_policy import ExtensionPolicy


class ReceiverMainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.extension_policy = ExtensionPolicy.from_config(config.allowed_extensions, config.blocked_extensions)
        self.setWindowTitle("Safe Media Transfer - Receiver")
        self.resize(780, 600)

        self._receive_thread: QThread | None = None
        self._receive_worker: ReceiveWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)

        self.destination_input = QLineEdit(str(config.storage.default_destination))
        self.bind_ip_input = QLineEdit(config.network.bind_ip)
        self.bind_ip_input.setToolTip("Use this computer's LAN IP address, e.g. 192.168.50.2")
        self.port_input = QLineEdit(str(config.network.port))
        self.port_input.setMaximumWidth(90)
        self.pairing_input = QLineEdit(config.security.pairing_code)
        self.pairing_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pairing_input.setPlaceholderText("Same code as on the sender (min. 12 characters)")
        self.status_label = make_status_label("Stopped")
        self.log_output = make_log_view()

        self.browse_button = QPushButton("Browse...")
        self.start_button = make_primary(QPushButton("Start Listener"))
        self.stop_button = QPushButton("Stop Listener")
        self.stop_button.setEnabled(False)
        self.settings_button = QPushButton("Settings")

        destination_row = QHBoxLayout()
        destination_row.addWidget(self.destination_input)
        destination_row.addWidget(self.browse_button)
        listen_row = QHBoxLayout()
        listen_row.addWidget(self.bind_ip_input)
        listen_row.addWidget(QLabel("Port"))
        listen_row.addWidget(self.port_input)

        form = QFormLayout()
        form.addRow("Destination Root", destination_row)
        form.addRow("Bind IP", listen_row)
        form.addRow("Pairing Code", self.pairing_input)

        button_row = QHBoxLayout()
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)
        button_row.addStretch()
        button_row.addWidget(self.status_label)

        listener_box = QGroupBox("Listener")
        listener_layout = QVBoxLayout()
        listener_layout.addLayout(form)
        listener_layout.addLayout(button_row)
        listener_box.setLayout(listener_layout)

        log_box = QGroupBox("Log")
        log_layout = QVBoxLayout()
        log_layout.addWidget(self.log_output)
        log_box.setLayout(log_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 12, 16, 16)
        layout.addLayout(make_header(
            "Safe Media Transfer", "Receiver: every file is checked again before it is saved", self.settings_button
        ))
        layout.addWidget(listener_box)
        layout.addWidget(log_box, 1)

        central.setLayout(layout)

        self.browse_button.clicked.connect(self._choose_destination)
        self.start_button.clicked.connect(self._start_listener)
        self.stop_button.clicked.connect(self._stop_listener)
        self.settings_button.clicked.connect(self._open_settings)

    def _choose_destination(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if folder:
            self.destination_input.setText(folder)

    def _start_listener(self) -> None:
        destination_root = self.destination_input.text().strip()
        bind_ip = self.bind_ip_input.text().strip()
        port_text = self.port_input.text().strip()

        if not destination_root or not bind_ip or not port_text:
            QMessageBox.warning(self, "Missing values", "Destination root, bind IP, and port are required.")
            return
        try:
            pairing_code = validate_pairing_code(self.pairing_input.text())
            port = int(port_text)
        except (AuthError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid values", str(exc))
            return
        if self._receive_thread is not None:
            self._append_log("Listener already running.")
            return

        self._receive_thread = QThread(self)
        self._receive_worker = ReceiveWorker(
            bind_host=bind_ip,
            port=port,
            destination_root=destination_root,
            pairing_code=pairing_code,
            config=self.config,
            extension_policy=self.extension_policy,
        )
        self._receive_worker.moveToThread(self._receive_thread)

        self._receive_thread.started.connect(self._receive_worker.start_listening)
        self._receive_worker.started_signal.connect(self._listener_started)
        self._receive_worker.stopped_signal.connect(self._listener_stopped)
        self._receive_worker.failed.connect(self._worker_failed)
        self._receive_worker.event.connect(self._append_log)

        self._receive_thread.start()
        self._set_running(True)
        set_status(self.status_label, "Starting...", "busy")
        self._append_log("Starting listener...")

    def _stop_listener(self) -> None:
        if self._receive_worker is not None:
            self._receive_worker.stop_listening()

        if self._receive_thread is not None:
            self._receive_thread.quit()
            self._receive_thread.wait()
            self._receive_thread.deleteLater()
            self._receive_thread = None
            self._receive_worker = None
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

    def _listener_started(self) -> None:
        set_status(self.status_label, "Listening", "ok")
        self._append_log("Receiver is listening.")

    def _listener_stopped(self) -> None:
        set_status(self.status_label, "Stopped", "idle")
        self._append_log("Receiver stopped.")

    def _worker_failed(self, message: str) -> None:
        if self._receive_thread is not None:
            self._receive_thread.quit()
            self._receive_thread.wait()
            self._receive_thread.deleteLater()
            self._receive_thread = None
            self._receive_worker = None
        self._set_running(False)
        set_status(self.status_label, "Error", "error")
        self._append_log(f"Error: {message}")
        QMessageBox.critical(self, "Receiver error", message)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec()

    def _append_log(self, message: str) -> None:
        self.log_output.append(message)