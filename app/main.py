from __future__ import annotations

import logging
import sqlite3
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

from app.config import APP_DIR, APP_NAME, DEFAULT_DATA_DIR, DEFAULT_DB_PATH, STATE_DIR
from app.controllers import MainWindow
from app.repositories import Database
from app.services.subject_statistics_export import export_subject_statistics
from app.test_mode import TestMainWindow, TestWorkspace, is_trial_subject
from app.ui.brand_icon import StartupSplash, application_icon

LOGGER = logging.getLogger(__name__)


def configure_logging(log_dir: Path = STATE_DIR) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "study_app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])


def run() -> int:
    arguments = sys.argv[1:]
    if len(arguments) != len(set(arguments)) or any(
        argument not in {"-t", "-ss"} for argument in arguments
    ):
        print("Cách dùng: python main.py [-t] [-ss]", file=sys.stderr)
        return 2
    test_mode = "-t" in arguments
    statistics_mode = "-ss" in arguments
    workspace = TestWorkspace.default() if test_mode else None
    try:
        if workspace is not None:
            workspace.prepare()
        configure_logging(workspace.root if workspace is not None else STATE_DIR)
    except (OSError, ValueError) as exc:
        print(f"Không thể chuẩn bị thư mục ứng dụng: {exc}", file=sys.stderr)
        return 1
    if statistics_mode:
        from app.services.data_scanner import DataScannerService
        from tools.analyze_mock_exam_frequency import generate_reports

        database: Database | None = None
        try:
            database = Database(workspace.database_path if workspace else DEFAULT_DB_PATH)
            data_dir = (
                workspace.data_dir
                if workspace is not None
                else Path(database.load_app_settings(DEFAULT_DATA_DIR).data_dir)
            )
            output_file = (
                APP_DIR / "docs" / "Test_Ver" / "subject_statistics.json"
                if test_mode
                else APP_DIR / "docs" / "subject_statistics.json"
            )
            report_path = export_subject_statistics(
                database, data_dir, output_file, test_mode=test_mode
            )
            exam_pool_paths: dict[str, frozenset[str]] = {}
            if workspace is not None:
                for subject in DataScannerService(workspace.data_dir).scan():
                    if not is_trial_subject(subject.name):
                        continue
                    allowed = workspace.exam_paths(subject)
                    if allowed is not None:
                        exam_pool_paths[subject.name] = allowed
            figures = generate_reports(
                database.path,
                output_file.parent,
                allowed_paths_by_subject=exam_pool_paths,
            )
            if not figures:
                raise ValueError("Không có môn học để tạo biểu đồ EDA.")
            print(f"Đã cập nhật thống kê môn học: {report_path}")
            for subject_name, png_path, csv_path in figures:
                print(f"{subject_name}: {png_path} | {csv_path}")
            return 0
        except (OSError, sqlite3.Error, ValueError) as exc:
            LOGGER.error("Không thể cập nhật thống kê môn học: %s", exc)
            print(f"Không thể cập nhật thống kê môn học: {exc}", file=sys.stderr)
            return 1
        finally:
            if database is not None:
                database.close()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    application = QApplication([sys.argv[0]] if test_mode else sys.argv)
    application.setApplicationName(APP_NAME)
    application.setOrganizationName("Local Study App")
    application.setWindowIcon(application_icon())
    database: Database | None = None
    splash: StartupSplash | None = None
    try:
        splash = StartupSplash()
        splash.show()
        application.processEvents()
        database = Database(workspace.database_path if workspace else DEFAULT_DB_PATH)
        window = (
            TestMainWindow(database, workspace)
            if workspace is not None
            else MainWindow(database)
        )
        window.setWindowIcon(application.windowIcon())
        splash.finished.connect(window.show)
        splash.start()
        code = application.exec_()
        return code
    except Exception as exc:  # pragma: no cover - fatal GUI fallback
        if splash is not None:
            splash.close()
        LOGGER.exception("Ứng dụng dừng do lỗi không xử lý")
        QMessageBox.critical(None, "Lỗi khởi động", f"Không thể khởi động ứng dụng:\n{exc}")
        return 1
    finally:
        if database is not None:
            database.close()
