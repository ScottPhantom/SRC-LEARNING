from __future__ import annotations

import csv
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from app.domain.models import ExamConfig, FeedbackMode
from app.repositories.database import Database
from app.services.data_scanner import DataScannerService
from app.services.exam import ExamService
from app.services.question_bank_updates import QuestionBankUpdateChecker


PROGRESS_TABLES = (
    "card_progress", "flash_sessions", "flash_session_items", "cram_cycles",
    "cram_items", "exam_attempts", "exam_answers", "question_error_stats",
)


def make_subject(data: Path, name: str = "CPV301"):
    path = data / name / "Selections_1_choose" / "Q001.png"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (120, 80), "white").save(path)
    write_answer(path.parent.parent, "A")
    return next(subject for subject in DataScannerService(data).scan() if subject.name == name)


def write_answer(subject: Path, answer: str) -> None:
    with (subject / "answers.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerows([("image_name", "correct_answer"), ("Selections_1_choose/Q001.png", answer)])


def progress_snapshot(database: Database):
    return {
        table: [tuple(row) for row in database._connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in PROGRESS_TABLES
    }


@pytest.fixture
def legacy_profile(tmp_path: Path):
    publisher = make_subject(tmp_path / "publisher" / "DATA")
    publisher_db = Database(tmp_path / "publisher.sqlite3")
    publisher_db.sync_questions(publisher.questions, [publisher.name])
    checker = QuestionBankUpdateChecker(publisher_db, (0, 0.9, 0.25, 0.1))
    checker.check_subject(publisher)
    for answer in ("B", "C", "D"):
        write_answer(publisher.path, answer)
        assert checker.check_subject(publisher).applied
    publisher_db.close()

    data = tmp_path / "client" / "DATA"
    shutil.copytree(publisher.path, data / publisher.name)
    ail = make_subject(data, "AIL303m")
    subjects = DataScannerService(data).scan()
    cpv = next(subject for subject in subjects if subject.name == "CPV301")
    database = Database(tmp_path / "client" / "study_progress.sqlite3")
    database.sync_questions([q for subject in subjects for q in subject.questions], [s.name for s in subjects])
    QuestionBankUpdateChecker(database, (0, 0.9, 0.25, 0.1)).check_subject(ail)
    database.create_flash_session(ail.name, [ail.questions[0].id])
    database.create_cram_cycle(ail.name, 17, [[ail.questions[0].id]])
    database.rate_card(ail.questions[0].id, True)
    database.rate_card(cpv.questions[0].id, True)
    database.record_question_attempt(cpv.questions[0].id, True)
    exam = ExamService(database, cpv.questions, {cpv.questions[0].relative_path: "D"})
    session = exam.create_session(ExamConfig(
        subject=cpv.name, categories=(cpv.questions[0].category,), question_count=1,
        duration_minutes=1, feedback_mode=FeedbackMode.DEFERRED,
    ))
    session.set_answer("D")
    session.submit()
    try:
        yield database, cpv, ail
    finally:
        database.close()


def test_recover_imported_v4_without_changing_progress_or_active_ail_sessions(legacy_profile):
    database, cpv, ail = legacy_profile
    assert database.recorded_bank_version(cpv.name) is None
    assert database.latest_bank_version(cpv.name) == 1  # Legacy display fallback, not a row.
    before = progress_snapshot(database)
    files = {path.name: path.read_bytes() for path in (cpv.path / "answer_versions").iterdir()}
    checker = QuestionBankUpdateChecker(database, (0, 0.9, 0.25, 0.1))
    result = checker.check_subject(cpv)
    assert not result.errors and not result.changes
    assert database.recorded_bank_version(cpv.name) == 4
    assert database.recorded_bank_version(ail.name) == 1
    assert progress_snapshot(database) == before
    assert {path.name: path.read_bytes() for path in (cpv.path / "answer_versions").iterdir()} == files
    assert database.active_flash_session(ail.name) is not None
    assert database.active_cram_cycle(ail.name) is not None
    metadata = [tuple(row) for row in database._connection.execute("SELECT * FROM question_bank_versions ORDER BY subject,bank_version")]
    assert not checker.check_subject(cpv).errors  # Recovery is idempotent.
    assert progress_snapshot(database) == before
    assert [tuple(row) for row in database._connection.execute("SELECT * FROM question_bank_versions ORDER BY subject,bank_version")] == metadata


def test_verify_only_does_not_repair_or_write_any_metadata(legacy_profile):
    database, cpv, _ail = legacy_profile
    before = progress_snapshot(database)
    result = QuestionBankUpdateChecker(database, (0, 0.9, 0.25, 0.1)).check_subject(cpv, apply=False)
    assert not result.errors and result.bank_version == 4
    assert database.recorded_bank_version(cpv.name) is None
    assert progress_snapshot(database) == before


def test_repairing_ail_own_missing_metadata_preserves_both_active_sessions(legacy_profile):
    database, _cpv, ail = legacy_profile
    with database.transaction() as connection:
        connection.execute("DELETE FROM question_revisions WHERE subject=?", (ail.name,))
        connection.execute("DELETE FROM question_bank_versions WHERE subject=?", (ail.name,))
    before = progress_snapshot(database)
    result = QuestionBankUpdateChecker(database, (0, 0.9, 0.25, 0.1)).check_subject(ail)
    assert not result.errors and not result.changes
    assert database.recorded_bank_version(ail.name) == 1
    assert progress_snapshot(database) == before
    assert database.active_flash_session(ail.name) is not None
    assert database.active_cram_cycle(ail.name) is not None


@pytest.mark.parametrize("broken", ["answer_snapshot", "manifest_snapshot", "foreign_subject"])
def test_recovery_fails_closed_on_inconsistent_snapshot_without_losing_progress(legacy_profile, broken):
    database, cpv, _ail = legacy_profile
    versions = cpv.path / "answer_versions"
    if broken == "answer_snapshot":
        (versions / "answers.v4.csv").write_text("image_name,correct_answer\nSelections_1_choose/Q001.png,A\n")
    elif broken == "manifest_snapshot":
        (versions / "manifest.v4.json").write_text("{}")
    else:
        active = versions / "manifest.json"
        payload = json.loads(active.read_text())
        payload["subject"] = "OTHER101"
        active.write_text(json.dumps(payload))
    before = progress_snapshot(database)
    result = QuestionBankUpdateChecker(database, (0, 0.9, 0.25, 0.1)).check_subject(cpv)
    assert result.errors
    assert database.recorded_bank_version(cpv.name) is None
    assert progress_snapshot(database) == before


def test_existing_contradictory_sqlite_history_is_not_overwritten(legacy_profile):
    database, cpv, _ail = legacy_profile
    with database.transaction() as connection:
        connection.execute("INSERT INTO question_bank_versions(subject,bank_version,active,created_at,question_count) VALUES(?,1,1,'existing',1)", (cpv.name,))
    before = progress_snapshot(database)
    result = QuestionBankUpdateChecker(database, (0, 0.9, 0.25, 0.1)).check_subject(cpv)
    assert result.errors and "không tự ghi đè" in result.errors[0]
    assert database.recorded_bank_version(cpv.name) == 1
    assert progress_snapshot(database) == before


def test_failed_revision_insert_rolls_back_the_new_version_row(legacy_profile):
    database, cpv, _ail = legacy_profile
    with database.transaction() as connection:
        connection.execute("CREATE TRIGGER fail_restore BEFORE INSERT ON question_revisions WHEN NEW.subject='CPV301' BEGIN SELECT RAISE(ABORT,'simulated metadata failure'); END")
    before = progress_snapshot(database)
    with pytest.raises(sqlite3.IntegrityError, match="simulated metadata failure"):
        QuestionBankUpdateChecker(database, (0, 0.9, 0.25, 0.1)).restore_missing_baseline(cpv)
    assert database.recorded_bank_version(cpv.name) is None
    assert progress_snapshot(database) == before


def test_reinstall_uses_local_sqlite_baseline_instead_of_resetting_to_v1(legacy_profile):
    database, cpv, _ail = legacy_profile
    checker = QuestionBankUpdateChecker(database, (0, 0.9, 0.25, 0.1))
    assert not checker.check_subject(cpv).errors
    before = progress_snapshot(database)
    shutil.rmtree(cpv.path / "answer_versions")  # Only the temporary test course.
    result = checker.check_subject(cpv)
    assert not result.errors and result.initialized and not result.changes
    assert result.bank_version == database.recorded_bank_version(cpv.name) == 4
    assert (cpv.path / "answer_versions" / "answers.v4.csv").is_file()
    assert progress_snapshot(database) == before


def test_approved_answer_only_update_is_not_overridden_by_unchanged_image(tmp_path):
    subject = make_subject(tmp_path / "DATA")
    database = Database(tmp_path / "progress.sqlite3")
    try:
        database.sync_questions(subject.questions, [subject.name])
        checker = QuestionBankUpdateChecker(database, (0, 0.9, 0.25, 0.1))
        assert checker.check_subject(subject).initialized
        write_answer(subject.path, "B")
        result = checker.check_subject(subject)
        assert result.applied and result.bank_version == 2
        assert result.updated[0].new_answer == "B"
        assert checker._read_answers(subject.path / "answers.csv")[subject.questions[0].relative_path] == "B"
    finally:
        database.close()
