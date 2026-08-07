from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

from app.config import APP_NAME, DEFAULT_DB_PATH, STATE_DIR
from app.controllers import MainWindow
from app.repositories import Database

LOGGER = logging.getLogger(__name__)


def configure_logging() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        STATE_DIR / "study_app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])


def run() -> int:
    configure_logging()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setOrganizationName("Local Study App")
    try:
        database = Database(DEFAULT_DB_PATH)
        window = MainWindow(database)
        window.show()
        code = application.exec_()
        database.close()
        return code
    except Exception as exc:  # pragma: no cover - fatal GUI fallback
        LOGGER.exception("Ứng dụng dừng do lỗi không xử lý")
        QMessageBox.critical(None, "Lỗi khởi động", f"Không thể khởi động ứng dụng:\n{exc}")
        return 1
