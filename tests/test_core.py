from __future__ import annotations

import csv
import logging
import random
import sqlite3
import unicodedata
from pathlib import Path

import pytest
from PIL import Image

from app.domain.models import (
    ExamConfig,
    ExamQuestion,
    FeedbackMode,
    Question,
    QuestionErrorStat,
    normalize_answer,
)
from app.repositories.answer_key import AnswerKeyRepository
from app.repositories.database import Database
from app.services.adaptive import AdaptiveReviewService
from app.services.data_scanner import DataScannerService
from app.services.exam import ExamResult, ExamService
from app.services.study import CrammingService, FlashcardService


def make_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 60), "white").save(path)


def make_questions(root: Path, amount: int, category: str = "Selections_1_choose"):
    subject = root / "TEST101"
    for index in range(amount):
        make_image(subject / category / f"Câu {index + 1}.png")
    return DataScannerService(root).scan()[0]


def test_scanner_handles_unicode_and_categories(tmp_path: Path) -> None:
    make_questions(tmp_path / "DATA", 3)
    make_image(tmp_path / "DATA" / "TEST101" / "True_False" / "Câu đúng sai.jpg")
    subjects = DataScannerService(tmp_path / "DATA").scan()
    assert len(subjects) == 1
    assert subjects[0].question_count == 4
    assert subjects[0].category_counts == {
        "Selections_1_choose": 3,
        "True_False": 1,
    }
    assert len({q.id for q in subjects[0].questions}) == 4


def test_answer_key_load_validate_and_report(tmp_path: Path) -> None:
    data = tmp_path / "DATA"
    subject = make_questions(data, 2)
    multiple_path = data / "TEST101" / "Selections_Multiple_choose" / "Nhiều.png"
    make_image(multiple_path)
    subject = DataScannerService(data).scan()[0]
    with (subject.path / "answers.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["image_name", "correct_answer"])
        writer.writerow(["Selections_1_choose/Câu 1.png", "b"])
        writer.writerow(["Selections_1_choose/Câu 2.png", "ZZ"])
        writer.writerow(["Selections_Multiple_choose/Nhiều.png", "DCA"])
    report = AnswerKeyRepository().load(subject.path, subject.questions)
    assert report.file_found
    assert report.total_rows == 3
    assert report.valid_count == 2
    assert report.answers["Selections_1_choose/Câu 1.png"] == "B"
    assert report.answers["Selections_Multiple_choose/Nhiều.png"] == "ACD"
    assert "Selections_1_choose/Câu 2.png" in report.invalid
    assert "Selections_1_choose/Câu 2.png" in report.missing


def test_answer_key_matches_windows_subject_prefix_basename_and_unicode(
    tmp_path: Path, caplog
) -> None:
    data = tmp_path / "DATA"
    subject = make_questions(data, 3)
    names = [question.relative_path for question in subject.questions]
    decomposed_name = unicodedata.normalize("NFD", names[0]).replace("/", "\\")
    with (subject.path / "answers.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([" image_name ", " correct_answer "])
        writer.writerow([decomposed_name, "A"])
        writer.writerow([f"{subject.name}/{names[1]}", "B"])
        writer.writerow([Path(names[2]).name, "C"])
    with caplog.at_level(logging.INFO, logger="app.repositories.answer_key"):
        report = AnswerKeyRepository().load(subject.path, subject.questions)
    assert report.valid_count == 3
    assert not report.missing
    assert "total_rows=3, mapped=3, rejected=0" in caplog.text


def test_answer_key_missing_file_logs_expected_absolute_path(
    tmp_path: Path, caplog
) -> None:
    subject = make_questions(tmp_path / "DATA", 2)
    with caplog.at_level(logging.WARNING, logger="app.repositories.answer_key"):
        report = AnswerKeyRepository().load(subject.path, subject.questions)
    assert not report.file_found
    assert report.csv_path == (subject.path / "answers.csv").resolve()
    assert len(report.missing) == 2
    assert str(report.csv_path) in caplog.text


def test_normalize_answer() -> None:
    assert normalize_answer(" d, b b a ") == "ABD"
    assert normalize_answer("xyz") == ""


def test_flashcard_persists_position_and_progress(tmp_path: Path) -> None:
    subject = make_questions(tmp_path / "DATA", 3)
    database = Database(tmp_path / "progress.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    service = FlashcardService(database, subject.questions)
    state = service.resume_or_start()
    first_id = state.question.id
    state = service.rate_current(False)
    assert state.position == 1
    resumed = FlashcardService(database, subject.questions).resume_or_start()
    assert resumed.position == 1
    assert database.card_stats(subject.name)["learning"] == 1
    assert first_id in database.learning_question_ids(subject.name)
    database.close()


def test_flashcard_restart_deletes_active_session_and_returns_to_first(
    tmp_path: Path,
) -> None:
    subject = make_questions(tmp_path / "DATA", 3)
    database = Database(tmp_path / "flash-restart.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    service = FlashcardService(database, subject.questions)
    service.resume_or_start()
    old_session_id = service.session_id
    service.rate_current(False)

    restarted = service.restart()

    old_row = database._connection.execute(
        "SELECT id FROM flash_sessions WHERE id=?", (old_session_id,)
    ).fetchone()
    assert old_row is None
    assert service.session_id != old_session_id
    assert restarted.position == 0
    assert not restarted.completed
    assert len(service.order) == 3
    database.close()


def test_cramming_rounds_unique_and_wrong_requeues(tmp_path: Path) -> None:
    subject = make_questions(tmp_path / "DATA", 23)
    ids = [q.id for q in subject.questions]
    rounds = CrammingService.build_rounds(ids, seed=42)
    assert [len(round_) for round_ in rounds] == [10, 10, 3]
    assert sorted(qid for round_ in rounds for qid in round_) == sorted(ids)
    database = Database(tmp_path / "progress.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    service = CrammingService(database, subject.questions)
    first = service.start_new()
    assert first.round_total == 10
    assert first.round_mastered == 0
    first_id = first.question.id
    second = service.rate_current(False)
    assert second.question.id != first_id
    assert second.remaining == 10
    assert second.round_mastered == 0
    third = service.rate_current(True)
    assert third.round_mastered == 1
    assert third.remaining == 9
    resumed = CrammingService(database, subject.questions).resume_or_start()
    assert resumed.question.id == third.question.id
    assert resumed.wrong == 1
    database.close()


def test_cramming_multiple_choice_requires_exact_set_match(tmp_path: Path) -> None:
    question = Question(
        id="multiple-exact",
        subject="TEST101",
        category="Selections_Multiple_choose",
        relative_path="Selections_Multiple_choose/Câu exact.png",
        absolute_path=Path("Câu exact.png"),
        correct_answer="ABD",
    )

    assert CrammingService.is_answer_correct(question, "DBA")
    assert not CrammingService.is_answer_correct(question, "AB")
    assert not CrammingService.is_answer_correct(question, "ABCD")
    assert not CrammingService.is_answer_correct(question, "ACD")

    subject = make_questions(
        tmp_path / "DATA", 1, category="Selections_Multiple_choose"
    )
    database = Database(tmp_path / "cram-exact.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    service = CrammingService(
        database,
        subject.questions,
        {subject.questions[0].relative_path: "ABD"},
    )
    before = service.start_new()
    assert not service.is_answer_correct(before.question, "AB")
    after = service.rate_current(False)
    assert after.question.id == before.question.id
    assert after.wrong == 1
    assert after.remaining == 1
    database.close()


def test_cramming_289_questions_creates_short_final_round() -> None:
    ids = [f"question-{index}" for index in range(289)]
    rounds = CrammingService.build_rounds(ids, seed=2026)
    assert len(rounds) == 29
    assert all(len(round_) == 10 for round_ in rounds[:-1])
    assert len(rounds[-1]) == 9
    assert len({qid for round_ in rounds for qid in round_}) == 289


def test_cramming_single_item_wrong_then_correct(tmp_path: Path) -> None:
    subject = make_questions(tmp_path / "DATA", 1)
    database = Database(tmp_path / "progress.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    service = CrammingService(database, subject.questions)
    state = service.start_new()
    assert service.rate_current(False).question.id == state.question.id
    completed = service.rate_current(True)
    assert completed.completed
    stat = database.question_error_stats([state.question.id])[state.question.id]
    assert stat.total_attempts == 2
    assert stat.wrong_count == 1
    assert stat.error_rate == pytest.approx(0.5)
    reopened = CrammingService(database, subject.questions)
    assert reopened.resume_or_start().completed
    assert not reopened.start_new().completed
    database.close()


def test_exam_pool_grading_and_history(tmp_path: Path) -> None:
    subject = make_questions(tmp_path / "DATA", 4)
    database = Database(tmp_path / "progress.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    answers = {question.relative_path: "A" for question in subject.questions}
    service = ExamService(database, subject.questions, answers)
    config = ExamConfig(
        subject=subject.name,
        categories=("Selections_1_choose",),
        question_count=3,
        duration_minutes=30,
        feedback_mode=FeedbackMode.DEFERRED,
    )
    session = service.create_session(config)
    session.set_answer("a")
    session.current_index = 1
    session.set_answer("B")
    result = session.submit()
    assert result.total == 3
    assert result.correct == 1
    assert result.unanswered == 1
    assert len(database.exam_history(subject.name)) == 1
    assert len(database.exam_detail(result.attempt_id)) == 3
    stats = database.question_error_stats(
        [item.question.id for item in session.items]
    )
    attempted = [item for item in session.items if item.selected_answer]
    unanswered = [item for item in session.items if not item.selected_answer]
    assert sorted(stats[item.question.id].wrong_count for item in attempted) == [0, 1]
    assert all(stats[item.question.id].total_attempts == 1 for item in attempted)
    assert all(stats[item.question.id].total_attempts == 0 for item in unanswered)
    with pytest.raises(ValueError):
        session.submit()
    database.close()


def test_delete_multiple_exam_attempts_cascades_answer_details(
    tmp_path: Path,
) -> None:
    subject = make_questions(tmp_path / "DATA", 3)
    database = Database(tmp_path / "delete-exams.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    answers = {question.relative_path: "A" for question in subject.questions}
    service = ExamService(database, subject.questions, answers)
    config = ExamConfig(
        subject=subject.name,
        categories=("Selections_1_choose",),
        question_count=2,
        duration_minutes=30,
        feedback_mode=FeedbackMode.DEFERRED,
    )
    attempt_ids = [service.create_session(config).submit().attempt_id for _ in range(3)]

    deleted = database.delete_exam_attempts(
        [attempt_ids[0], attempt_ids[2], attempt_ids[0], 999_999]
    )

    assert deleted == 2
    assert [row["id"] for row in database.exam_history()] == [attempt_ids[1]]
    assert not database.exam_detail(attempt_ids[0])
    assert database.exam_detail(attempt_ids[1])
    assert not database.exam_detail(attempt_ids[2])
    assert database.delete_exam_attempts([]) == 0
    database.close()


def test_exam_weighted_sampling_prioritizes_frequent_errors(tmp_path: Path) -> None:
    subject = make_questions(tmp_path / "DATA", 2)
    database = Database(tmp_path / "weighted.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    difficult, known = subject.questions
    for _ in range(10):
        database.record_question_attempt(difficult.id, correct=False)
    database.rate_card(known.id, known=True)
    answers = {question.relative_path: "A" for question in subject.questions}
    service = ExamService(
        database,
        subject.questions,
        answers,
        rng=random.Random(2026),
    )
    config = ExamConfig(
        subject=subject.name,
        categories=("Selections_1_choose",),
        question_count=1,
        duration_minutes=30,
        feedback_mode=FeedbackMode.DEFERRED,
    )

    chosen_ids = [service.create_session(config).current.question.id for _ in range(200)]

    assert chosen_ids.count(difficult.id) > 180
    assert chosen_ids.count(difficult.id) > chosen_ids.count(known.id)
    difficult_stat = database.question_error_stats([difficult.id])[difficult.id]
    known_stat = database.question_error_stats([known.id])[known.id]
    assert service.question_weight(difficult_stat) > service.question_weight(known_stat)
    full_exam = service.create_session(
        ExamConfig(
            subject=subject.name,
            categories=("Selections_1_choose",),
            question_count=2,
            duration_minutes=30,
            feedback_mode=FeedbackMode.DEFERRED,
        )
    )
    assert len({item.question.id for item in full_exam.items}) == 2
    database.close()


def test_exam_weight_decreases_after_many_correct_answers() -> None:
    never_attempted = QuestionErrorStat("new")
    frequently_wrong = QuestionErrorStat(
        "hard", total_attempts=10, wrong_count=8
    )
    repeatedly_correct = QuestionErrorStat(
        "mastered", total_attempts=20, wrong_count=0
    )

    assert ExamService.question_weight(repeatedly_correct) < ExamService.question_weight(
        never_attempted
    )
    assert ExamService.question_weight(never_attempted) < ExamService.question_weight(
        frequently_wrong
    )


def test_exam_result_pass_threshold_is_inclusive() -> None:
    config = ExamConfig(
        subject="TEST101",
        categories=("Selections_1_choose",),
        question_count=1,
        duration_minutes=30,
        feedback_mode=FeedbackMode.DEFERRED,
    )
    boundary = ExamResult(
        attempt_id=1,
        config=config,
        total=1,
        correct=1,
        unanswered=0,
        score=7.0,
        score_percent=70.0,
        items=[],
    )
    below = ExamResult(
        attempt_id=2,
        config=config,
        total=1,
        correct=0,
        unanswered=0,
        score=6.99,
        score_percent=69.9,
        items=[],
    )

    assert boundary.passed and boundary.status == "PASS"
    assert not below.passed and below.status == "FAIL"


def test_adaptive_review_service_ranks_errors_and_excludes_mastered(
    tmp_path: Path,
) -> None:
    subject = make_questions(tmp_path / "DATA", 3)
    database = Database(tmp_path / "weakness.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    most_difficult, sometimes_wrong, always_correct = subject.questions
    database.record_question_attempt(most_difficult.id, correct=False)
    database.record_question_attempt(most_difficult.id, correct=False)
    database.record_question_attempt(sometimes_wrong.id, correct=False)
    database.record_question_attempt(sometimes_wrong.id, correct=True)
    for _ in range(3):
        database.record_question_attempt(always_correct.id, correct=True)
    answers = {question.relative_path: "A" for question in subject.questions}

    ranked = AdaptiveReviewService(
        database,
        subject.questions,
        answers,
    ).top_errors_by_category()

    entries = ranked["Selections_1_choose"]
    assert [entry.question.id for entry in entries] == [
        most_difficult.id,
        sometimes_wrong.id,
    ]
    assert [entry.error_rate for entry in entries] == [1.0, 0.5]
    assert entries[0].correct_answer == "A"
    assert AdaptiveReviewService(
        database, subject.questions, answers
    ).top_errors_by_category(limit=1)["Selections_1_choose"] == entries[:1]
    database.close()


def test_exam_rejects_count_over_valid_pool(tmp_path: Path) -> None:
    subject = make_questions(tmp_path / "DATA", 2)
    database = Database(tmp_path / "progress.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    service = ExamService(database, subject.questions, {subject.questions[0].relative_path: "A"})
    config = ExamConfig(
        subject=subject.name,
        categories=("Selections_1_choose",),
        question_count=2,
        duration_minutes=30,
        feedback_mode=FeedbackMode.IMMEDIATE,
    )
    with pytest.raises(ValueError, match="Chỉ có 1 câu"):
        service.create_session(config)
    database.close()


def test_multiple_choice_is_graded_as_an_unordered_set(tmp_path: Path) -> None:
    subject = make_questions(tmp_path / "DATA", 1, "Selections_Multiple_choose")
    database = Database(tmp_path / "progress.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    question = subject.questions[0]
    service = ExamService(database, subject.questions, {question.relative_path: "ACD"})
    session = service.create_session(
        ExamConfig(
            subject=subject.name,
            categories=("Selections_Multiple_choose",),
            question_count=1,
            duration_minutes=1,
            feedback_mode=FeedbackMode.IMMEDIATE,
        )
    )
    session.set_answer("DCA")
    assert session.confirm_current()
    assert session.submit().correct == 1
    database.close()


def test_partial_credit_formula_rewards_correct_and_penalizes_wrong() -> None:
    question = Question(
        id="multiple",
        subject="TEST",
        category="Selections_Multiple_choose",
        relative_path="Selections_Multiple_choose/Câu.png",
        absolute_path=Path("Câu.png"),
        correct_answer="ABC",
    )
    item = ExamQuestion(question=question, selected_answer="AB")
    assert item.calculate_score(2.5) == pytest.approx(5.0 / 3.0)
    item.selected_answer = "ABD"
    assert item.calculate_score(2.5) == pytest.approx(2.5 / 3.0)
    item.selected_answer = "D"
    assert item.calculate_score(2.5) == 0.0
    item.selected_answer = "ABC"
    assert item.calculate_score(2.5) == 2.5


def test_exam_saves_partial_score_as_two_decimal_float(tmp_path: Path) -> None:
    data = tmp_path / "DATA"
    make_questions(data, 1)
    make_image(data / "TEST101" / "Selections_Multiple_choose" / "Câu nhiều.png")
    subject = DataScannerService(data).scan()[0]
    database = Database(tmp_path / "partial.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    answers = {
        question.relative_path: (
            "ABC" if question.category == "Selections_Multiple_choose" else "A"
        )
        for question in subject.questions
    }
    session = ExamService(database, subject.questions, answers).create_session(
        ExamConfig(
            subject=subject.name,
            categories=("Selections_1_choose", "Selections_Multiple_choose"),
            question_count=2,
            duration_minutes=1,
            feedback_mode=FeedbackMode.DEFERRED,
        )
    )
    for index, item in enumerate(session.items):
        session.current_index = index
        session.set_answer("AB" if item.question.is_multiple else "A")
    result = session.submit()
    assert result.score == 8.33
    assert result.score_percent == 83.3
    attempt = database.exam_history(subject.name)[0]
    assert attempt["score"] == 8.33
    assert isinstance(attempt["score"], float)
    awarded = sorted(row["awarded_score"] for row in database.exam_detail(result.attempt_id))
    assert awarded == [3.33, 5.0]
    database.close()


def test_database_migrates_legacy_exam_scores(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_version(version INTEGER NOT NULL);
        INSERT INTO schema_version VALUES(1);
        CREATE TABLE exam_attempts(
            id INTEGER PRIMARY KEY, subject TEXT, config_json TEXT, started_at TEXT,
            submitted_at TEXT, submit_reason TEXT, total INTEGER, correct INTEGER,
            unanswered INTEGER, score_percent REAL NOT NULL
        );
        CREATE TABLE exam_answers(
            attempt_id INTEGER, position INTEGER, question_id TEXT, relative_path TEXT,
            selected_answer TEXT, correct_answer TEXT, is_correct INTEGER,
            PRIMARY KEY(attempt_id, position)
        );
        INSERT INTO exam_attempts VALUES(
            1,'OLD','{}','start','end','user',2,1,0,50.0
        );
        INSERT INTO exam_answers VALUES(1,0,'q1','q1.png','A','A',1);
        INSERT INTO exam_answers VALUES(1,1,'q2','q2.png','B','A',0);
        """
    )
    connection.commit()
    connection.close()
    database = Database(path)
    backups = list(tmp_path.glob("legacy.pre-v1.*.sqlite3"))
    assert backups == [database.migration_backup_path]
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup.execute("SELECT version FROM schema_version").fetchone()[0] == 1
        assert (
            backup.execute("SELECT score_percent FROM exam_attempts").fetchone()[0]
            == 50.0
        )
        legacy_columns = {
            row[1] for row in backup.execute("PRAGMA table_info(exam_attempts)")
        }
        assert "score" not in legacy_columns
    attempt = database.exam_history()[0]
    assert attempt["score"] == 5.0
    assert [row["awarded_score"] for row in database.exam_detail(1)] == [5.0, 0.0]
    version = database._connection.execute("SELECT version FROM schema_version").fetchone()[0]
    assert version == 4
    tables = {
        row["name"]
        for row in database._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "question_error_stats" in tables
    database.close()


def test_database_does_not_backup_new_or_current_schema(tmp_path: Path) -> None:
    path = tmp_path / "current.sqlite3"
    database = Database(path)
    assert database.migration_backup_path is None
    database.close()

    reopened = Database(path)
    assert reopened.migration_backup_path is None
    reopened.close()
    assert list(tmp_path.glob("current.pre-v*.*.sqlite3")) == []


def test_database_aborts_migration_when_backup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "backup-failure.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_version(version INTEGER NOT NULL);
            INSERT INTO schema_version VALUES(1);
            CREATE TABLE preserved(value TEXT NOT NULL);
            INSERT INTO preserved VALUES('still here');
            """
        )

    def fail_backup(self: Database, previous_version: int) -> Path:
        raise OSError(f"Không thể backup schema v{previous_version}")

    monkeypatch.setattr(Database, "_create_migration_backup", fail_backup)
    with pytest.raises(OSError, match="Không thể backup schema v1"):
        Database(path)

    with sqlite3.connect(path) as unchanged:
        assert (
            unchanged.execute("SELECT version FROM schema_version").fetchone()[0] == 1
        )
        assert (
            unchanged.execute("SELECT value FROM preserved").fetchone()[0]
            == "still here"
        )
        tables = {
            row[0]
            for row in unchanged.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "exam_attempts" not in tables


def test_thirty_fully_correct_questions_total_exactly_ten(tmp_path: Path) -> None:
    subject = make_questions(tmp_path / "DATA", 30)
    database = Database(tmp_path / "thirty.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    service = ExamService(
        database,
        subject.questions,
        {question.relative_path: "A" for question in subject.questions},
    )
    session = service.create_session(
        ExamConfig(
            subject=subject.name,
            categories=("Selections_1_choose",),
            question_count=30,
            duration_minutes=30,
            feedback_mode=FeedbackMode.DEFERRED,
        )
    )
    for index in range(30):
        session.current_index = index
        session.set_answer("A")
    result = session.submit()
    assert result.score == 10.0
    assert database.exam_history()[0]["score"] == 10.0
    database.close()


def test_answer_key_cramming_replaces_legacy_self_assessment_cycle(
    tmp_path: Path,
) -> None:
    subject = make_questions(tmp_path / "DATA", 3)
    database = Database(tmp_path / "cram-mode-migration.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    legacy = CrammingService(database, subject.questions)
    legacy_state = legacy.start_new()
    answers = {question.relative_path: "A" for question in subject.questions}
    upgraded = CrammingService(database, subject.questions, answers)
    upgraded_state = upgraded.resume_or_start()
    assert upgraded_state.cycle_id != legacy_state.cycle_id
    latest = database.latest_cram_cycle(subject.name)
    assert latest["grading_mode"] == "answer_key_v1"
    assert database.active_cram_cycle(subject.name)["id"] == upgraded_state.cycle_id
    database.close()
