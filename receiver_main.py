from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.config.loader import load_app_config
from app.logging_setup.logging_factory import configure_logging
from app.ui.receiver.main_window import ReceiverMainWindow
from app.ui.style import apply_app_style
from app.utils.platform_paths import resolve_config_path


def main() -> int:
    config_path = resolve_config_path(Path("config.toml"))
    config = load_app_config(config_path)
    configure_logging(config)
    logging.getLogger(__name__).info("receiver.application_started")

    app = QApplication(sys.argv)
    apply_app_style(app)
    window = ReceiverMainWindow(config)
    window.resize(780, 600)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())