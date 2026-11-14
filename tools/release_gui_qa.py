"""Release gate: approved CPV ZIP -> real import dialog -> persisted answer bank.

All profiles are disposable, explicitly marked QA directories. No developer
DATA/database is read or copied. The Windows mode drives only the new EXE's
process tree; synthetic AIL flash/cram sessions must remain byte-for-byte equal.
"""
from __future__ import annotations

import argparse
import csv
import faulthandler
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
PROGRESS_TABLES = (
    "card_progress", "flash_sessions", "flash_session_items", "cram_cycles",
    "cram_items", "exam_attempts", "exam_answers", "question_error_stats",
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def marked_workspace(root: Path) -> Path:
    root = root.resolve()
    if root in {PROJECT, Path.home(), Path(root.anchor)}:
        raise ValueError("QA requires a separate disposable directory")
    marker = root / ".src-release-qa"
    if root.exists() and any(root.iterdir()) and not marker.is_file():
        raise ValueError(f"Refusing to reuse an unmarked, nonempty directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text("Disposable SRC Learning release QA data only.\n", encoding="utf-8")
    return root


def prepare(root: Path, archive: Path | None = None) -> dict:
    from app.config import CATALOG_CSV_URL
    from app.services.data_package_installer import DataPackageCatalog, DataPackageInstaller
    from app.services.package_catalog_source import PackageCatalogSource

    content = None
    for attempt in range(3):
        try:
            content = PackageCatalogSource._fetch(CATALOG_CSV_URL)
            break
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2)
    assert content is not None
    catalog = DataPackageCatalog.from_sheet_csv(content)
    bundled = DataPackageCatalog.bundled()
    public = {p.subject: asdict(p) for p in catalog._by_file_id.values() if p.enabled}
    fallback = {p.subject: asdict(p) for p in bundled._by_file_id.values() if p.enabled}
    if public != fallback:
        raise ValueError("Public GOOGLE_IDS and bundled DSS metadata differ; review before releasing")
    package = next(p for p in catalog._by_file_id.values() if p.subject == "CPV301")
    target = root / "CPV301.zip"
    if not target.exists():
        if archive is not None:
            shutil.copyfile(archive, target)
        else:
            DataPackageInstaller._download_with_gdown(
                package.file_id, target, package.archive_size, lambda *_args: None
            )
    if target.stat().st_size != package.archive_size or digest(target) != package.sha256:
        raise ValueError("CPV public ZIP does not match the approved metadata")
    (root / "catalog.csv").write_bytes(content)
    payload = {"cpv": asdict(package), "catalog": public}
    (root / "metadata.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def readonly_database(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def progress_snapshot(path: Path) -> dict:
    with readonly_database(path) as connection:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() for table in PROGRESS_TABLES}


def ail_files(profile: Path) -> dict[str, str]:
    ail = profile / "DATA" / "AIL303m"
    return {str(p.relative_to(ail)): digest(p) for p in ail.rglob("*") if p.is_file()}


def version(path: Path) -> int | None:
    with readonly_database(path) as connection:
        row = connection.execute("SELECT bank_version FROM question_bank_versions WHERE subject='CPV301' AND active=1").fetchone()
    return int(row[0]) if row else None


def make_profile(root: Path, name: str, scenario: str, package: dict) -> dict:
    from PIL import Image
    from app.domain.models import ExamConfig, FeedbackMode
    from app.repositories.database import Database
    from app.services.data_package_installer import DataPackageInstaller
    from app.services.data_scanner import DataScannerService
    from app.services.exam import ExamService
    from app.services.question_bank_updates import QuestionBankUpdateChecker

    profile = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=root))
    data = profile / "DATA"
    publisher_version = None
    if scenario != "fresh":
        unpacked = profile / "unpacked"
        DataPackageInstaller._safe_extract(root / "CPV301.zip", unpacked, lambda *_args: None)
        source, count = DataPackageInstaller._validate_subject(unpacked, "CPV301", lambda *_args: None)
        assert count == package["expected_questions"]
        cpv = data / "CPV301"
        shutil.copytree(source, cpv)
        publisher_version = json.loads((cpv / "answer_versions" / "manifest.json").read_text(encoding="utf-8"))["bank_version"]
        if scenario == "add":
            # Controlled prior state: one real question absent, not a claim
            # about a historically published ZIP. The incoming ZIP is unmodified.
            previous = DataScannerService(data).scan()[0]
            missing = previous.questions[-1]
            missing.absolute_path.unlink()
            answers = QuestionBankUpdateChecker._read_answers(cpv / "answers.csv")
            answers.pop(missing.relative_path)
            with (cpv / "answers.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["image_name", "correct_answer"])
                writer.writerows(answers.items())
            shutil.rmtree(cpv / "answer_versions")

    ail = data / "AIL303m"
    for index in (1, 2):
        image = ail / "Selections_1_choose" / f"QA{index}.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (200, 100), "white").save(image)
    with (ail / "answers.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerows([("image_name", "correct_answer"), ("Selections_1_choose/QA1.png", "A"), ("Selections_1_choose/QA2.png", "B")])
    subjects = DataScannerService(data).scan()
    database_path = profile / "study_progress.sqlite3"
    database = Database(database_path)
    try:
        database.set_setting("data_dir", str(data))
        database.sync_questions([q for s in subjects for q in s.questions], [s.name for s in subjects])
        ail_subject = next(s for s in subjects if s.name == "AIL303m")
        QuestionBankUpdateChecker(database, (0, 0.9, 0.25, 0.1)).check_subject(ail_subject)
        ids = [q.id for q in ail_subject.questions]
        flash = database.create_flash_session("AIL303m", ids)
        database.update_flash_position(flash, 1, complete=False)
        cram = database.create_cram_cycle("AIL303m", 31, [ids])
        database.rate_cram_item(cram, ids[0], False)
        database.rate_card(ids[0], True)
        cpv_subject = next((s for s in subjects if s.name == "CPV301"), None)
        if cpv_subject is not None:
            q = cpv_subject.questions[0]
            database.rate_card(q.id, True)
            answers = QuestionBankUpdateChecker._read_answers(cpv_subject.path / "answers.csv")
            exam = ExamService(database, [q], answers)
            session = exam.create_session(ExamConfig(
                subject="CPV301", categories=(q.category,), question_count=1,
                duration_minutes=1, feedback_mode=FeedbackMode.DEFERRED,
            ))
            session.set_answer(answers[q.relative_path])
            session.submit()
    finally:
        database.close()
    return {
        "path": profile, "database": database_path,
        "expected_questions": package["expected_questions"],
        "allow_cpv_grading_version_advance": scenario == "add",
        "progress": progress_snapshot(database_path), "ail_files": ail_files(profile),
        "startup_version": publisher_version if scenario == "legacy" else (1 if scenario == "add" else None),
        "installed_version": publisher_version if scenario == "legacy" else (2 if scenario == "add" else 1),
    }


def check_preserved(state: dict, expected_version: int) -> None:
    assert version(state["database"]) == expected_version
    after = progress_snapshot(state["database"])
    if state["allow_cpv_grading_version_advance"]:
        # Normal ADD publishes a new bank tag on saved CPV exams. All saved
        # answers, scores, original bank versions and AIL state must be equal.
        with readonly_database(state["database"]) as connection:
            fields = [column[1] for column in connection.execute("PRAGMA table_info(exam_attempts)")]
        subject_index = fields.index("subject")
        grade_index = fields.index("graded_bank_version")
        before_rows = state["progress"]["exam_attempts"]
        assert len(after["exam_attempts"]) == len(before_rows)
        normalized = []
        for previous, current in zip(before_rows, after["exam_attempts"], strict=True):
            values = list(current)
            if values[subject_index] == "CPV301":
                assert values[grade_index] == expected_version
                values[grade_index] = previous[grade_index]
            normalized.append(tuple(values))
        after["exam_attempts"] = normalized
    assert after == state["progress"], "Progress/history or AIL sessions changed"
    assert ail_files(state["path"]) == state["ail_files"], "Synthetic AIL files changed"
    with readonly_database(state["database"]) as connection:
        count = connection.execute("SELECT COUNT(*) FROM questions WHERE subject='CPV301' AND active=1").fetchone()[0]
    assert count == state["expected_questions"]


def qt_qa(root: Path, metadata: dict) -> list[dict]:
    print("Qt GUI QA: importing application modules", flush=True)
    from PyQt5.QtCore import QTimer, Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from app.config import CATALOG_CSV_URL
    from app.controllers.main_controller import MainWindow
    from app.repositories.database import Database
    from app.services.data_package_installer import DataPackageCatalog, DataPackageInstaller
    from app.services.package_catalog_source import PackageCatalogSource

    print("Qt GUI QA: creating QApplication", flush=True)
    app = QApplication.instance() or QApplication([])
    print("Qt GUI QA: QApplication ready", flush=True)
    reports = []
    for scenario in ("legacy", "add", "fresh"):
        print(f"Qt GUI QA: preparing {scenario} profile", flush=True)
        state = make_profile(root, f"qt-{scenario}", scenario, metadata["cpv"])
        print(f"Qt GUI QA: opening {scenario} window", flush=True)
        database = Database(state["database"])
        window = MainWindow(database)
        window.resize(1280, 800)
        window.show()
        catalog_content = (root / "catalog.csv").read_bytes()
        window._catalog_source = PackageCatalogSource(CATALOG_CSV_URL, state["path"] / "catalog.csv", fetch=lambda _url: catalog_content)

        def local_download(_id, output, _size, _progress):
            shutil.copyfile(root / "CPV301.zip", output)
            return output

        window._data_package_installer = DataPackageInstaller(DataPackageCatalog.from_sheet_csv(catalog_content), local_download)

        def wait_until(predicate, timeout=30):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                app.processEvents()
                if predicate():
                    return
                QTest.qWait(20)
            dialog = window._data_import_dialog
            window.grab().save(str(root / f"qt-{scenario}-timeout.png"))
            raise AssertionError(f"GUI QA timed out: status={dialog.status_label.text() if dialog else None!r}; scan={window._scan_running}; rescan={window._rescan_requested}; install={window._data_install_task is not None}; pending={window._pending_data_install_result is not None}; catalog={window._catalog_task is not None}; unexpected={unexpected}")

        timer = QTimer()
        timer.setInterval(30)
        unexpected = []

        def confirm_replacement():
            for widget in app.topLevelWidgets():
                if isinstance(widget, QMessageBox) and widget.isVisible():
                    # macOS intentionally leaves QMessageBox.windowTitle empty.
                    # Match the scoped subject/message, never approve AIL prompts.
                    if widget.text().startswith("Môn CPV301 đã tồn tại."):
                        button = next(b for b in widget.buttons() if b.text() == "Xác minh và thay thế")
                        # click() sends the normal Qt clicked signal without a
                        # headless window-manager focus/activation dependency.
                        button.click()
                    else:
                        unexpected.append({"title": widget.windowTitle(), "text": widget.text()})
                        widget.reject()

        timer.timeout.connect(confirm_replacement)
        timer.start()
        try:
            wait_until(lambda: not window._scan_running and not window._rescan_requested)
            assert version(state["database"]) == state["startup_version"]
            messages = []
            for iteration in (1, 2):
                print(f"Qt GUI QA: {scenario} import {iteration}", flush=True)
                QTest.mouseClick(window.app_header.data_import_button, Qt.LeftButton)
                dialog = window._data_import_dialog
                assert dialog is not None
                wait_until(lambda: dialog.isVisible() and dialog.install_button.isVisible())
                dialog.code_input.setFocus()
                QTest.keyClicks(dialog.code_input, metadata["cpv"]["file_id"])
                assert dialog.code_input.text() == metadata["cpv"]["file_id"]
                QTest.qWait(50)
                QTest.mouseClick(dialog.install_button, Qt.LeftButton)
                wait_until(lambda: dialog._completed or bool(dialog.status_label.property("error")) or bool(unexpected))
                assert not unexpected, f"Unexpected session prompt: {unexpected}"
                assert dialog._completed, dialog.status_label.text()
                assert dialog.progress_bar.value() == 100
                assert f"answer bank v{state['installed_version']}" in dialog.status_label.text()
                messages.append(dialog.status_label.text())
                print(dialog.status_label.text(), flush=True)
                dialog.grab().save(str(root / f"qt-{scenario}-{iteration}.png"))
                check_preserved(state, state["installed_version"])
                QTest.mouseClick(dialog.install_button, Qt.LeftButton)
                wait_until(lambda: window._data_import_dialog is None)
            reports.append({"scenario": scenario, "status": "PASS", "messages": messages, "preserved_progress_and_two_ail_sessions": True, "bank_version": state["installed_version"]})
        finally:
            timer.stop()
            if window._data_import_dialog is not None:
                window._data_import_dialog.set_running(False)
                window._data_import_dialog.reject()
            window.close()
            window.thread_pool.waitForDone(5000)
            app.processEvents()
            database.close()
    return reports


def windows_qa(root: Path, metadata: dict, executable: Path) -> list[dict]:
    if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("Native EXE QA must run on the isolated GitHub Windows runner")
    import psutil
    from pywinauto import Desktop

    desktop = Desktop(backend="uia")
    reports = []
    for scenario in ("legacy", "add"):
        state = make_profile(root, f"exe-{scenario}", scenario, metadata["cpv"])
        environment = os.environ.copy()
        environment.update(SRC_LEARNING_STATE_DIR=str(state["path"]), QT_QPA_PLATFORM="windows")
        process = subprocess.Popen([str(executable.resolve())], env=environment, cwd=state["path"])
        main = None
        gui_pid = None
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                assert process.poll() is None, "EXE exited during startup"
                pids = [process.pid, *[p.pid for p in psutil.Process(process.pid).children(recursive=True)]]
                for pid in pids:
                    candidate = desktop.window(title="SRC LEARNING", process=pid)
                    if candidate.exists(timeout=0.2):
                        main, gui_pid = candidate, pid
                        break
                if main is not None and version(state["database"]) == state["startup_version"]:
                    break
                time.sleep(0.5)
            assert main is not None and gui_pid is not None, "No real EXE main window"
            assert version(state["database"]) == state["startup_version"]
            main.wait("visible enabled ready", timeout=30)
            main.child_window(title="Thêm môn học", control_type="Button").click_input()
            # Qt exposes owned modal dialogs as Window children of the main
            # window in UIA, not as Desktop's top-level windows.
            dialog = main.child_window(title="Thêm môn học", control_type="Window")
            dialog.wait("visible", timeout=15)
            dialog.child_window(control_type="Edit", found_index=0).set_edit_text(metadata["cpv"]["file_id"])
            dialog.child_window(title="Tải và cài đặt", control_type="Button").click_input()
            confirmation = main.child_window(title="Thay thế dữ liệu môn học", control_type="Window")
            confirmation.wait("visible", timeout=45)
            confirmation.child_window(title="Xác minh và thay thế", control_type="Button").click_input()
            deadline = time.monotonic() + 180
            message = ""
            while time.monotonic() < deadline:
                texts = [control.window_text() for control in dialog.descendants(control_type="Text")]
                error = next((text for text in texts if "Không hoàn tất" in text or "Không thể cài" in text), "")
                assert not error, error
                prefix = f"Đã cài CPV301 với {metadata['cpv']['expected_questions']} câu hỏi;"
                message = next((text for text in texts if text.startswith(prefix)), "")
                if message and dialog.child_window(title="Hoàn tất", control_type="Button").exists(timeout=0.2):
                    break
                time.sleep(0.5)
            assert f"answer bank v{state['installed_version']}" in message, f"Import did not finish: {message}"
            dialog.capture_as_image().save(root / f"exe-{scenario}-complete.png")
            check_preserved(state, state["installed_version"])
            dialog.child_window(title="Hoàn tất", control_type="Button").click_input()
            main.capture_as_image().save(root / f"exe-{scenario}-home.png")
            main.close()
            assert process.wait(timeout=30) == 0, "EXE did not exit cleanly"
            reports.append({"scenario": scenario, "status": "PASS", "message": message, "bank_version": state["installed_version"], "preserved_progress_and_two_ail_sessions": True, "clean_exit": True})
        except Exception:
            if main is not None:
                try:
                    main.capture_as_image().save(root / f"exe-{scenario}-failure.png")
                    main.print_control_identifiers(filename=str(root / f"exe-{scenario}-controls.txt"))
                except Exception:
                    pass
            raise
        finally:
            if process.poll() is None:
                # Only the process tree started above, never another app by name.
                for child in psutil.Process(process.pid).children(recursive=True):
                    child.terminate()
                process.terminate()
                process.wait(timeout=15)
    return reports


def main() -> int:
    for output_stream in (sys.stdout, sys.stderr):
        if output_stream is not None and hasattr(output_stream, "reconfigure"):
            output_stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "qt", "windows"))
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    root = marked_workspace(args.workdir)
    print(f"Release GUI QA mode: {args.mode}", flush=True)
    os.environ["SRC_LEARNING_STATE_DIR"] = str(root / "unused-source-profile")
    if args.mode == "prepare":
        print(json.dumps(prepare(root, args.archive), ensure_ascii=False, indent=2))
        return 0
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    assert digest(root / "CPV301.zip") == metadata["cpv"]["sha256"]
    if args.mode == "qt":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        with (root / "qt-crash-log.txt").open("w", encoding="utf-8") as crash_log:
            faulthandler.enable(file=crash_log, all_threads=True)
            try:
                reports = qt_qa(root, metadata)
            finally:
                faulthandler.disable()
    else:
        if args.exe is None:
            parser.error("--exe is required for native Windows QA")
        reports = windows_qa(root, metadata, args.exe)
    report = {"status": "PASS", "mode": args.mode, "commit": os.environ.get("GITHUB_SHA"), "cpv": metadata["cpv"], "cases": reports}
    if args.mode == "windows":
        report["executable_sha256"] = digest(args.exe)
    (root / f"{args.mode}-gui-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
