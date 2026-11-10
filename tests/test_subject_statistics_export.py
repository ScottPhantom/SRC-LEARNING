"""CLI statistics reports must match the in-app dashboard and isolate test data."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from app import main as app_main
from app.repositories.database import Database
from app.services.data_scanner import DataScannerService
from app.services.subject_statistics_export import export_subject_statistics
from app.test_mode import TestWorkspace as TrialWorkspace


def make_subject(data_dir: Path, name: str, *, count: int = 2) -> Path:
    subject_dir = data_dir / name
    category_dir = subject_dir / "Selections_1_choose"
    category_dir.mkdir(parents=True)
    rows = ["image_name,correct_answer"]
    for index in range(1, count + 1):
        image_name = f"Selections_1_choose/Q{index:03d}.png"
        Image.new("RGB", (8, 8), "white").save(subject_dir / image_name)
        rows.append(f"{image_name},A")
    (subject_dir / "answers.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return subject_dir


def read_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_export_uses_dashboard_statistics_and_separate_trial_database(
    tmp_path: Path,
) -> None:
    normal_data = tmp_path / "DATA"
    trial_data = tmp_path / "trial" / "data"
    make_subject(normal_data, "MAIN101", count=3)
    make_subject(normal_data, "SHADOW_t")
    make_subject(trial_data, "TRIAL101_t")
    make_subject(trial_data, "NOT_A_TRIAL")
    normal_questions = DataScannerService(normal_data).scan()[0].questions
    trial_questions = next(
        subject.questions
        for subject in DataScannerService(trial_data).scan()
        if subject.name == "TRIAL101_t"
    )

    normal_db = Database(tmp_path / "normal.sqlite3")
    trial_db = Database(tmp_path / "trial" / "test_progress.sqlite3")
    try:
        normal_db.sync_questions(normal_questions, ["MAIN101"])
        normal_db.rate_card(normal_questions[0].id, True)
        normal_db.rate_card(normal_questions[1].id, False)
        normal_db.record_question_attempt(normal_questions[1].id, False)
        normal_db.record_question_attempt(normal_questions[1].id, True)
        trial_db.sync_questions(trial_questions, ["TRIAL101_t"])
        trial_db.rate_card(trial_questions[0].id, False)

        normal_path = tmp_path / "docs" / "subject_statistics.json"
        trial_path = tmp_path / "docs" / "Test_Ver" / "subject_statistics.json"
        export_subject_statistics(normal_db, normal_data, normal_path)
        export_subject_statistics(trial_db, trial_data, trial_path, test_mode=True)

        normal = read_report(normal_path)
        trial = read_report(trial_path)
        assert normal["mode"] == "main"
        assert set(normal["subjects"]) == {"MAIN101"}
        main_subject = normal["subjects"]["MAIN101"]
        assert main_subject["card_stats"] == {"new": 1, "known": 1, "learning": 1}
        assert main_subject["answer_key"]["valid_count"] == 3
        category = main_subject["categories"]["Selections_1_choose"]
        assert [row["card_state"] for row in category["not_learned"]] == [
            "learning", "new"
        ]
        assert [row["image_name"] for row in category["not_learned"]] == [
            normal_questions[1].relative_path,
            normal_questions[2].relative_path,
        ]
        assert category["top_errors"][0]["wrong_count"] == 1
        assert category["top_errors"][0]["total_attempts"] == 2
        assert category["top_errors"][0]["error_rate"] == 0.5
        assert trial["mode"] == "test"
        assert set(trial["subjects"]) == {"TRIAL101_t"}
        assert trial["subjects"]["TRIAL101_t"]["card_stats"] == {
            "new": 1, "known": 0, "learning": 1
        }
        assert normal_db.card_stats("MAIN101")["known"] == 1
    finally:
        normal_db.close()
        trial_db.close()


def test_cli_ss_routes_reports_and_rejects_old_test_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_subject(tmp_path / "DATA", "MAIN101", count=1)
    make_subject(tmp_path / "DATA", "MAIN102", count=1)
    workspace = TrialWorkspace(tmp_path / ".src-learning-test")
    make_subject(workspace.data_dir, "TRIAL101_t", count=1)
    make_subject(workspace.data_dir, "TRIAL102_t", count=1)
    ail_trial = make_subject(workspace.data_dir, "AIL303M_t", count=155)
    (ail_trial / "exam_first_154.json").write_text(
        json.dumps(
            {
                "subject": "AIL303M_t",
                "exam_image_names": [
                    f"Selections_1_choose/Q{index:03d}.png"
                    for index in range(1, 155)
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(app_main, "APP_DIR", tmp_path)
    monkeypatch.setattr(app_main, "STATE_DIR", tmp_path)
    monkeypatch.setattr(app_main, "DEFAULT_DB_PATH", tmp_path / "normal.sqlite3")
    monkeypatch.setattr(app_main, "DEFAULT_DATA_DIR", tmp_path / "DATA")
    monkeypatch.setattr(app_main, "configure_logging", lambda _path: None)
    monkeypatch.setattr(
        app_main.TestWorkspace, "default", classmethod(lambda _cls: workspace)
    )

    monkeypatch.setattr(sys, "argv", ["main.py", "-t", "-ss"])
    assert app_main.run() == 0
    trial = read_report(tmp_path / "docs" / "Test_Ver" / "subject_statistics.json")
    assert set(trial["subjects"]) == {"AIL303M_t", "TRIAL101_t", "TRIAL102_t"}
    assert trial["subjects"]["AIL303M_t"]["question_count"] == 155
    assert not (tmp_path / "normal.sqlite3").exists()
    for subject in trial["subjects"]:
        report_dir = tmp_path / "docs" / "Test_Ver" / subject
        figures = list(report_dir.glob("Date-of-Statistical_*/*.png"))
        tables = list(report_dir.glob("Date-of-Statistical_*/*.csv"))
        assert len(figures) == len(tables) == 1
        with Image.open(figures[0]) as image:
            assert image.size == (1800, 1450)
        with tables[0].open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
            assert rows[0]["subject"] == subject
            assert len(rows) == (154 if subject == "AIL303M_t" else 1)
    assert not (tmp_path / "docs" / "MAIN101").exists()

    monkeypatch.setattr(sys, "argv", ["main.py", "-ss"])
    assert app_main.run() == 0
    normal = read_report(tmp_path / "docs" / "subject_statistics.json")
    assert set(normal["subjects"]) == {"MAIN101", "MAIN102"}
    assert trial["subjects"] != normal["subjects"]
    for subject in normal["subjects"]:
        report_dir = tmp_path / "docs" / subject
        assert len(list(report_dir.glob("Date-of-Statistical_*/*.png"))) == 1
        assert len(list(report_dir.glob("Date-of-Statistical_*/*.csv"))) == 1

    monkeypatch.setattr(sys, "argv", ["main.py", "-test"])
    assert app_main.run() == 2
    assert "[-t] [-ss]" in capsys.readouterr().err


def test_missing_trial_subject_does_not_erase_existing_progress(
    tmp_path: Path,
) -> None:
    normal_data = tmp_path / "normal"
    make_subject(normal_data, "MAIN101", count=1)
    question = DataScannerService(normal_data).scan()[0].questions[0]
    database = Database(tmp_path / "progress.sqlite3")
    try:
        database.sync_questions([question], ["MAIN101"])
        database.rate_card(question.id, True)
        with pytest.raises(ValueError, match="Không tìm thấy môn thử"):
            export_subject_statistics(
                database, normal_data, tmp_path / "Test_Ver" / "report.json",
                test_mode=True,
            )
        assert database.card_stats("MAIN101")["known"] == 1
        assert not (tmp_path / "Test_Ver" / "report.json").exists()
    finally:
        database.close()


def test_export_refuses_symlinked_report_directory_before_sync(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "DATA"
    make_subject(data_dir, "MAIN101", count=1)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "docs"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Nền tảng không cho tạo symlink")
    database = Database(tmp_path / "progress.sqlite3")
    try:
        with pytest.raises(ValueError, match="không an toàn"):
            export_subject_statistics(database, data_dir, link / "report.json")
        assert database.card_stats("MAIN101")["new"] == 0
        assert not (outside / "report.json").exists()
    finally:
        database.close()


def test_t_flag_opens_normal_looking_test_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = TrialWorkspace(tmp_path / ".src-learning-test")
    observed: dict[str, object] = {}

    class FakeApplication:
        @staticmethod
        def setAttribute(_attribute: object, _enabled: bool) -> None:
            pass

        def __init__(self, arguments: list[str]):
            observed["qt_arguments"] = arguments

        def setApplicationName(self, name: str) -> None:
            observed["name"] = name

        def setOrganizationName(self, _name: str) -> None:
            pass

        def setWindowIcon(self, icon: object) -> None:
            observed["application_icon"] = icon

        def windowIcon(self) -> object:
            return observed["application_icon"]

        def processEvents(self) -> None:
            pass

        def exec_(self) -> int:
            return 0

    class FakeDatabase:
        def __init__(self, path: Path):
            observed["database_path"] = path

        def close(self) -> None:
            observed["closed"] = True

    class FakeWindow:
        def __init__(self, _database: FakeDatabase, active_workspace: TrialWorkspace):
            observed["workspace"] = active_workspace

        def setWindowIcon(self, icon: object) -> None:
            observed["window_icon"] = icon

        def show(self) -> None:
            observed["shown"] = True

    class FakeSplash:
        def __init__(self) -> None:
            self.finished = self
            self._show_window = None

        def show(self) -> None:
            pass

        def connect(self, callback) -> None:
            self._show_window = callback

        def start(self) -> None:
            assert self._show_window is not None
            self._show_window()

    monkeypatch.setattr(app_main, "QApplication", FakeApplication)
    monkeypatch.setattr(app_main, "Database", FakeDatabase)
    monkeypatch.setattr(app_main, "TestMainWindow", FakeWindow)
    monkeypatch.setattr(app_main, "StartupSplash", FakeSplash)
    monkeypatch.setattr(app_main, "application_icon", lambda: "brand icon")
    monkeypatch.setattr(app_main, "configure_logging", lambda _path: None)
    monkeypatch.setattr(
        app_main.TestWorkspace, "default", classmethod(lambda _cls: workspace)
    )
    monkeypatch.setattr(sys, "argv", ["main.py", "-t"])

    assert app_main.run() == 0
    assert observed == {
        "qt_arguments": ["main.py"],
        "name": app_main.APP_NAME,
        "application_icon": "brand icon",
        "database_path": workspace.database_path,
        "workspace": workspace,
        "window_icon": "brand icon",
        "shown": True,
        "closed": True,
    }
