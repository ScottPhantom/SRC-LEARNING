"""Isolated MainWindow/native-EXE release gates for SSG105t 158 -> 369.

No learner profile is opened. CI reconstructs the installed v1 from the exact
158 unchanged records in v2, checked against a fingerprint of the historical
ZIP. The original v1 ZIP may instead be supplied for local source-GUI QA.
Course images/answer keys are never uploaded as CI verification artifacts.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from tools.flashcard_release_qa import native_test_display, native_window, progress_rows
from tools.release_gui_qa import digest, marked_workspace, readonly_database

REFERENCE = PROJECT / "tools/fixtures/ssg105t_v1_reference.json"
TARGET = "SSG105t"
SCENARIOS = ("fresh", "upgrade", "cancel-active")


def fingerprint(folder: Path, paths: list[str]) -> str:
    """Hash stable IDs, image bytes, normalized keys and effective choices."""
    from app.services.data_scanner import DataScannerService
    from app.services.question_bank_updates import QuestionBankUpdateChecker

    subject = DataScannerService(folder.parent)._scan_subject(folder)
    questions = {q.relative_path: q for q in subject.questions}
    answers = QuestionBankUpdateChecker._read_answers(folder / "answers.csv")
    records = [
        [path, questions[path].id, digest(questions[path].absolute_path), answers[path], list(questions[path].options)]
        for path in sorted(paths)
    ]
    return hashlib.sha256(json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def file_rows(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): digest(p) for p in folder.rglob("*") if p.is_file()}


def verify_archive(path: Path, package: dict) -> None:
    import zipfile

    assert path.stat().st_size == package["archive_size"] and digest(path) == package["sha256"], f"Unapproved ZIP: {path}"
    with zipfile.ZipFile(path) as bundle:
        assert bundle.testzip() is None, f"Corrupt ZIP: {path}"


def prepare(root: Path, v1: Path | None = None) -> dict:
    from app.services.data_package_installer import DataPackageInstaller

    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    sources = {}
    for name in (TARGET, "SSG105"):
        package = metadata["catalog"][name]
        assert package == reference["approved_packages"][name], "DSS metadata changed after approval"
        archive = root / f"{name}.zip"
        if not archive.exists():
            DataPackageInstaller._download_with_gdown(package["file_id"], archive, package["archive_size"], lambda *_: None)
        verify_archive(archive, package)
        unpacked = root / f"{name}-unpacked"
        if not unpacked.exists():
            DataPackageInstaller._safe_extract(archive, unpacked, lambda *_: None)
        folder, count = DataPackageInstaller._validate_subject(unpacked, name, lambda *_: None)
        assert count == package["expected_questions"]
        sources[name] = str(folder)
    assert fingerprint(Path(sources[TARGET]), reference["paths"]) == reference["fingerprint_sha256"], "v2 changed the original 158 records"
    if v1 is not None:
        verify_archive(v1, reference["archive"])
        unpacked = root / "historical-v1"
        if not unpacked.exists():
            DataPackageInstaller._safe_extract(v1, unpacked, lambda *_: None)
        folder, count = DataPackageInstaller._validate_subject(unpacked, TARGET, lambda *_: None)
        assert count == 158 and fingerprint(folder, reference["paths"]) == reference["fingerprint_sha256"]
        sources["v1"] = str(folder)
    result = {"sources": sources, "reference_sha256": digest(REFERENCE), "packages": reference["approved_packages"]}
    (root / "ssg105t-metadata.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def copy_course(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("answer_versions"))


def reconstruct_v1(source: Path, destination: Path, reference: dict) -> None:
    """Exact installed content, not a claim that CI downloaded the old ZIP."""
    copy_course(source, destination)
    keep = set(reference["paths"])
    from app.services.data_scanner import DataScannerService

    for question in DataScannerService(destination.parent)._scan_subject(destination).questions:
        if question.relative_path not in keep:
            question.absolute_path.unlink()
    for name in ("answers.csv", "question_metadata.csv"):
        path = destination / name
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = reader.fieldnames
            rows = [row for row in reader if row["image_name"] in keep]
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
    assert fingerprint(destination, reference["paths"]) == reference["fingerprint_sha256"]


def make_profile(root: Path, metadata: dict, scenario: str, mode: str) -> dict:
    from PIL import Image
    from app.domain.models import ExamConfig, FeedbackMode
    from app.repositories.database import Database
    from app.services.data_scanner import DataScannerService
    from app.services.exam import ExamService
    from app.services.question_bank_updates import QuestionBankUpdateChecker

    assert scenario in SCENARIOS
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    assert digest(REFERENCE) == metadata["reference_sha256"]
    profile = Path(tempfile.mkdtemp(prefix=f"ssg105t-{mode}-{scenario}-", dir=root))
    data = profile / "DATA"
    copy_course(Path(metadata["sources"]["SSG105"]), data / "SSG105")
    baseline = "not-installed"
    if scenario != "fresh":
        if "v1" in metadata["sources"]:
            copy_course(Path(metadata["sources"]["v1"]), data / TARGET)
            baseline = "historical-v1-zip"
        else:
            reconstruct_v1(Path(metadata["sources"][TARGET]), data / TARGET, reference)
            baseline = "v1-content-reconstructed-and-fingerprint-verified"
        assert fingerprint(data / TARGET, reference["paths"]) == reference["fingerprint_sha256"]
    ail = data / "AIL303m"
    (ail / "Selections_1_choose").mkdir(parents=True)
    for index in (1, 2):
        Image.new("RGB", (240, 160), "white").save(ail / "Selections_1_choose" / f"QA{index}.png")
    with (ail / "answers.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerows([("image_name", "correct_answer"), ("Selections_1_choose/QA1.png", "A"), ("Selections_1_choose/QA2.png", "B")])
    subjects = DataScannerService(data).scan()
    database_path = profile / "study_progress.sqlite3"
    database = Database(database_path)
    try:
        database.set_setting("data_dir", str(data))
        database.set_setting("theme", "dark" if scenario == "upgrade" else "light")
        database.sync_questions([q for s in subjects for q in s.questions], [s.name for s in subjects])
        for subject in subjects:
            result = QuestionBankUpdateChecker(database, (0, 0.9, 0.25, 0.1)).check_subject(subject)
            assert not result.errors and result.bank_version == 1
            ids = [q.id for q in subject.questions]
            for index, identifier in enumerate(ids[:4]):
                database.rate_card(identifier, index % 2 == 0)
            flash = database.create_flash_session(subject.name, ids[:8])
            active = subject.name != TARGET or scenario == "cancel-active"
            database.update_flash_position(flash, 1 if active else min(8, len(ids)), complete=not active)
            if active:
                cram = database.create_cram_cycle(subject.name, 23, [ids[:8]])
                database.rate_cram_item(cram, ids[0], False)
            answers = QuestionBankUpdateChecker._read_answers(subject.path / "answers.csv")
            service = ExamService(database, subject.questions[:2], answers)
            session = service.create_session(ExamConfig(subject=subject.name, categories=tuple({q.category for q in subject.questions[:2]}), question_count=2, duration_minutes=5, feedback_mode=FeedbackMode.DEFERRED))
            session.set_answer(answers[session.current.question.relative_path])
            # Keep a saved unanswered item too, to detect unintended regrading.
            session.submit()
    finally:
        database.close()
    return {
        "path": profile, "database": database_path, "scenario": scenario, "baseline": baseline,
        "progress": progress_rows(database_path),
        "protected_files": {name: file_rows(data / name) for name in ("SSG105", "AIL303m")},
        "baseline_files": file_rows(data / TARGET) if scenario != "fresh" else {},
    }


def check_preserved(state: dict, version: int, count: int) -> dict:
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    after = progress_rows(state["database"])
    for table, previous in state["progress"].items():
        current = after[table]
        if table in {"question_bank_versions", "question_revisions"}:
            assert [r for r in current if r["subject"] != TARGET] == [r for r in previous if r["subject"] != TARGET], f"Other course {table} changed"
            if table == "question_revisions":
                indexed = {(row["subject"], row["logical_id"], row["revision"]): row for row in current}
                assert all(indexed.get((row["subject"], row["logical_id"], row["revision"])) == row for row in previous), "Original question revisions were changed or removed"
            if version == 1 and count == 158:
                assert current == previous
            continue
        if table == "exam_attempts":
            current = [row.copy() for row in current]
            assert len(current) == len(previous)
            for old, new in zip(previous, current, strict=True):
                if old["subject"] == TARGET:
                    assert new["graded_bank_version"] == version
                    new["graded_bank_version"] = old["graded_bank_version"]
        assert current == previous, f"Saved progress/history/session changed: {table}"
    for name, files in state["protected_files"].items():
        assert file_rows(state["path"] / "DATA" / name) == files, f"{name} files/history changed"
    folder = state["path"] / "DATA" / TARGET
    assert fingerprint(folder, reference["paths"]) == reference["fingerprint_sha256"]
    for relative, original_digest in state["baseline_files"].items():
        if relative.startswith("answer_versions/") and relative != "answer_versions/manifest.json":
            assert digest(folder / relative) == original_digest, "The original answer-history snapshot changed"
    with readonly_database(state["database"]) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        bank = connection.execute("SELECT bank_version,question_count,added_count,updated_count,deleted_count FROM question_bank_versions WHERE subject=? AND active=1", (TARGET,)).fetchone()
        assert bank[:2] == (version, count), bank
        assert connection.execute("SELECT COUNT(*) FROM questions WHERE subject=? AND active=1", (TARGET,)).fetchone()[0] == count
        assert connection.execute("SELECT COUNT(*) FROM question_bank_versions WHERE subject=?", (TARGET,)).fetchone()[0] == version, "Repeat import created a phantom version"
        if version == 2:
            assert bank[2:] == (211, 0, 0), bank
            changes = connection.execute("SELECT change_type,COUNT(*) FROM question_bank_notification_changes WHERE subject=? AND bank_version=2 GROUP BY change_type", (TARGET,)).fetchall()
            assert changes == [("ADD", 211)], changes
    if count == 158:
        assert file_rows(folder) == state["baseline_files"], "Cancelled update modified files"
    return {"progress_and_history_preserved": True, "old_ssg105_unchanged": True, "ail_sessions_preserved": True, "original_158_preserved": True, "sqlite_integrity_ok": True}


def qt_qa(root: Path, metadata: dict) -> list[dict]:
    from PyQt5.QtCore import QTimer, Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from app.controllers.main_controller import MainWindow
    from app.repositories.database import Database

    app = QApplication.instance() or QApplication([])
    reports = []
    for scenario in SCENARIOS:
        print(f"SSG105t source GUI: {scenario}", flush=True)
        state = make_profile(root, metadata, scenario, "qt")
        database = Database(state["database"])
        window = MainWindow(database)
        window.resize(1280, 900)
        window.show()
        unexpected, prompts = [], []

        def wait(predicate, seconds=180):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                app.processEvents()
                if predicate():
                    return
                QTest.qWait(25)
            window.grab().save(str(root / f"ssg105t-qt-{scenario}-timeout.png"))
            dialog = window._data_import_dialog
            raise AssertionError(f"SSG105t GUI timeout: {dialog.status_label.text() if dialog else 'no dialog'}; unexpected={unexpected}")

        def handle_prompt():
            for widget in app.topLevelWidgets():
                if not isinstance(widget, QMessageBox) or not widget.isVisible():
                    continue
                text = widget.text()
                if text.startswith(f"Môn {TARGET} đã tồn tại."):
                    choice = "Xác minh và thay thế"
                elif scenario == "cancel-active" and text.startswith(f"Môn {TARGET} có phiên học đang hoạt động."):
                    choice = "Giữ phiên và hủy thao tác"
                else:
                    unexpected.append(text)
                    widget.reject()
                    continue
                prompts.append(choice)
                next(b for b in widget.buttons() if b.text() == choice).click()

        timer = QTimer()
        timer.timeout.connect(handle_prompt)
        timer.start(40)
        messages = []
        try:
            wait(lambda: not window._scan_running and not window._rescan_requested)
            for iteration in range(1, 2 if scenario == "cancel-active" else 3):
                QTest.mouseClick(window.app_header.data_import_button, Qt.LeftButton)
                dialog = window._data_import_dialog
                assert dialog is not None
                dialog.code_input.setFocus()
                QTest.keyClicks(dialog.code_input, metadata["packages"][TARGET]["file_id"])
                QTest.mouseClick(dialog.install_button, Qt.LeftButton)
                wait(lambda: dialog._completed or bool(dialog.status_label.property("error")) or "Đã giữ phiên học" in dialog.status_label.text() or bool(unexpected))
                assert not unexpected, unexpected
                messages.append(dialog.status_label.text())
                cancelled = scenario == "cancel-active"
                assert cancelled or dialog._completed, messages[-1]
                expected_version = 1 if scenario != "upgrade" else 2
                preservation = check_preserved(state, expected_version, 158 if cancelled else 369)
                if not cancelled:
                    assert dialog.progress_bar.value() == 100 and f"answer bank v{expected_version}" in messages[-1]
                    assert window.subjects[TARGET].question_count == 369
                    assert len(window.subjects["SSG105"].questions) == 456
                dialog.grab().save(str(root / f"ssg105t-qt-{scenario}-{iteration}.png"))
                if cancelled:
                    QTest.mouseClick(dialog.cancel_button, Qt.LeftButton)
                else:
                    QTest.mouseClick(dialog.install_button, Qt.LeftButton)
                wait(lambda: window._data_import_dialog is None)
            assert scenario != "cancel-active" or "Giữ phiên và hủy thao tác" in prompts
            reports.append({"scenario": scenario, "status": "PASS", "baseline": state["baseline"], "messages": messages, "bank_version": expected_version, "question_count": 158 if cancelled else 369, "repeat_import_no_extra_version": not cancelled, "active_target_cancel_preserved": cancelled, **preservation})
        finally:
            timer.stop()
            if window._data_import_dialog is not None:
                window._data_import_dialog.set_running(False)
                window._data_import_dialog.reject()
            window.close()
            window.thread_pool.waitForDone(10000)
            app.processEvents()
            database.close()
    return reports


def windows_qa(root: Path, metadata: dict, executable: Path) -> list[dict]:
    reports = []
    with native_test_display() as display:
        for scenario in SCENARIOS:
            print(f"SSG105t native Windows EXE GUI: {scenario}", flush=True)
            state = make_profile(root, metadata, scenario, "windows")
            messages = []
            expected_version = 2 if scenario == "upgrade" else 1
            cancelled = scenario == "cancel-active"
            with native_window(executable, state["path"], root, f"ssg105t-{scenario}") as (process, main):
                main.child_window(title="Môn học SSG105, 456 câu hỏi").wait("visible", timeout=60)
                for iteration in range(1, 2 if cancelled else 3):
                    main.child_window(title="Thêm môn học", control_type="Button").click_input()
                    dialog = main.child_window(title="Thêm môn học", control_type="Window")
                    dialog.wait("visible", timeout=15)
                    dialog.child_window(control_type="Edit", found_index=0).set_edit_text(metadata["packages"][TARGET]["file_id"])
                    dialog.child_window(title="Tải và cài đặt", control_type="Button").click_input()
                    if scenario != "fresh" or iteration > 1:
                        prompt = main.child_window(title="Thay thế dữ liệu môn học", control_type="Window")
                        prompt.wait("visible", timeout=60)
                        prompt.child_window(title="Xác minh và thay thế", control_type="Button").click_input()
                    if cancelled:
                        prompt = main.child_window(title="Hủy phiên học đang hoạt động", control_type="Window")
                        prompt.wait("visible", timeout=30)
                        prompt.child_window(title="Giữ phiên và hủy thao tác", control_type="Button").click_input()
                    deadline = time.monotonic() + 180
                    message = ""
                    while time.monotonic() < deadline:
                        texts = [c.window_text() for c in dialog.descendants(control_type="Text")]
                        error = next((s for s in texts if "Không thể cài" in s or "Không hoàn tất" in s or "Mã này chưa" in s), "")
                        assert not error, error
                        prefix = "Đã giữ phiên học;" if cancelled else f"Đã cài {TARGET} với 369 câu hỏi;"
                        message = next((s for s in texts if s.startswith(prefix)), "")
                        if message:
                            break
                        time.sleep(0.4)
                    assert message and (cancelled or f"answer bank v{expected_version}" in message), f"Incomplete import: {message}"
                    messages.append(message)
                    preservation = check_preserved(state, expected_version, 158 if cancelled else 369)
                    dialog.capture_as_image().save(root / f"ssg105t-windows-{scenario}-{iteration}.png")
                    dialog.child_window(title="Hủy" if cancelled else "Hoàn tất", control_type="Button").click_input()
                    if not cancelled:
                        main.child_window(title=f"Môn học {TARGET}, 369 câu hỏi").wait("visible", timeout=30)
                main.capture_as_image().save(root / f"ssg105t-windows-{scenario}-home.png")
                main.close()
                assert process.wait(timeout=30) == 0, "EXE did not exit cleanly"
            # Check persisted state after a second genuine EXE process opens.
            with native_window(executable, state["path"], root, f"ssg105t-{scenario}-reopen") as (process, main):
                main.child_window(title=f"Môn học {TARGET}, {158 if cancelled else 369} câu hỏi").wait("visible", timeout=60)
                check_preserved(state, expected_version, 158 if cancelled else 369)
                main.close()
                assert process.wait(timeout=30) == 0
            reports.append({"scenario": scenario, "status": "PASS", "baseline": state["baseline"], "messages": messages, "bank_version": expected_version, "question_count": 158 if cancelled else 369, "repeat_import_no_extra_version": not cancelled, "active_target_cancel_preserved": cancelled, "clean_exit": True, "reopen_preserved": True, "physical_mouse_gui": True, "display": display, **preservation})
    return reports


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "qt", "windows"))
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--v1", type=Path)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    root = marked_workspace(args.workdir)
    os.environ["SRC_LEARNING_STATE_DIR"] = str(root / "unused-ssg105t-profile")
    if args.mode == "prepare":
        print(json.dumps(prepare(root, args.v1), ensure_ascii=False, indent=2))
        return
    metadata = json.loads((root / "ssg105t-metadata.json").read_text(encoding="utf-8"))
    for name, package in metadata["packages"].items():
        verify_archive(root / f"{name}.zip", package)
    if args.mode == "qt":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cases = qt_qa(root, metadata)
    else:
        if args.exe is None:
            parser.error("--exe is required for native Windows QA")
        cases = windows_qa(root, metadata, args.exe)
    report = {"status": "PASS", "mode": args.mode, "platform": sys.platform, "commit": os.environ.get("GITHUB_SHA"), "packages": metadata["packages"], "reference_sha256": metadata["reference_sha256"], "cases": cases}
    if args.mode == "windows":
        report["executable_sha256"] = digest(args.exe)
    (root / f"ssg105t-{args.mode}-gui-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
