"""Shared look for the sender and receiver windows.

Colours come from the system palette, so light and dark themes both work.
"""

from __future__ import annotations

from PySide6.QtGui import QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

_STYLESHEET = """
QGroupBox {
    font-weight: 600;
    border: 1px solid palette(mid);
    border-radius: 6px;
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QPushButton[primary="true"] {
    background-color: palette(highlight);
    color: palette(highlighted-text);
    border: none;
    border-radius: 4px;
    padding: 7px 18px;
    font-weight: 600;
}
QPushButton[primary="true"]:disabled {
    background-color: palette(mid);
    color: palette(window);
}
QFrame#tile {
    background-color: palette(base);
    border: 1px solid palette(mid);
    border-radius: 6px;
}
QLabel#title {
    font-size: 15pt;
    font-weight: 600;
}
QLabel#status {
    padding: 4px 12px;
    border-radius: 11px;
    font-weight: 600;
}
QLabel#status[state="idle"]  { background-color: rgba(128, 128, 128, 0.20); }
QLabel#status[state="busy"]  { background-color: rgba(33, 150, 243, 0.25); }
QLabel#status[state="ok"]    { background-color: rgba(46, 160, 67, 0.28); }
QLabel#status[state="warn"]  { background-color: rgba(230, 160, 0, 0.30); }
QLabel#status[state="error"] { background-color: rgba(218, 54, 51, 0.30); }
"""


def apply_app_style(app: QApplication) -> None:
    # Fusion draws stylesheets the same way on Windows and Linux.
    app.setStyle("Fusion")
    app.setStyleSheet(_STYLESHEET)


def make_primary(button: QPushButton) -> QPushButton:
    button.setProperty("primary", True)
    return button


def make_muted(label: QLabel) -> QLabel:
    palette = label.palette()
    palette.setColor(QPalette.ColorRole.WindowText, palette.color(QPalette.ColorRole.PlaceholderText))
    label.setPalette(palette)
    return label


def make_status_label(text: str, state: str = "idle") -> QLabel:
    label = QLabel()
    label.setObjectName("status")
    set_status(label, text, state)
    return label


def set_status(label: QLabel, text: str, state: str) -> None:
    """state is one of idle, busy, ok, warn, error (see the stylesheet)."""
    label.setText(text)
    label.setProperty("state", state)
    label.style().unpolish(label)
    label.style().polish(label)


def make_log_view() -> QTextEdit:
    log = QTextEdit()
    log.setReadOnly(True)
    log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
    log.setPlaceholderText("Activity will appear here.")
    return log


def make_header(title: str, subtitle: str, *right: QWidget) -> QHBoxLayout:
    title_label = QLabel(title)
    title_label.setObjectName("title")
    text = QVBoxLayout()
    text.setSpacing(0)
    text.addWidget(title_label)
    text.addWidget(make_muted(QLabel(subtitle)))

    header = QHBoxLayout()
    header.addLayout(text)
    header.addStretch()
    for widget in right:
        header.addWidget(widget)
    return header
