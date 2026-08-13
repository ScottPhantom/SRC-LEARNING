from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image

from app.domain.models import ExamConfig, FeedbackMode
from app.repositories.answer_key import AnswerKeyRepository
from app.repositories.database import Database
from app.services.data_scanner import DataScannerService
from app.services.exam import ExamService
from app.services.question_bank_updates import QuestionBankUpdateChecker
from tools.analyze_mock_exam_frequency import load_rows


def make_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 60), "white").save(path)


def write_answers(subject_path: Path, rows: list[tuple[str, str]]) -> None:
    with (subject_path / "answers.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["image_name", "correct_answer"])
        writer.writerows(rows)


def scan_subject(data: Path):
    return DataScannerService(data).scan()[0]


def bootstrap(
    database: Database, subject, resolver=lambda _question: "A"
) -> QuestionBankUpdateChecker:
    database.sync_questions(subject.questions, [subject.name])
    checker = QuestionBankUpdateChecker(
        database, (0.0, 0.9, 0.25, 0.1), answer_resolver=resolver
    )
    result = checker.check_subject(subject)
    assert result.initialized
    assert not result.changes
    assert database.latest_bank_version(subject.name) == 1
    return checker


def test_add_creates_new_bank_version_and_only_resolves_new_question(
    tmp_path: Path,
) -> None:
    data = tmp_path / "DATA"
    subject_path = data / "TEST101"
    make_image(subject_path / "Selections_1_choose" / "Câu 1.png")
    write_answers(subject_path, [("Selections_1_choose/Câu 1.png", "A")])
    subject = scan_subject(data)
    database = Database(tmp_path / "progress.sqlite3")
    resolved: list[str] = []

    def resolver(question) -> str:
        resolved.append(question.relative_path)
        return "B"

    checker = bootstrap(database, subject, resolver)
    make_image(subject_path / "True_False" / "Câu 2.png")
    subject = scan_subject(data)
    database.sync_questions(subject.questions, [subject.name])

    result = checker.check_subject(subject)

    assert result.applied
    assert result.previous_version == 1
    assert result.bank_version == 2
    assert len(result.added) == 1
    assert not result.updated and not result.deleted
    assert resolved == ["True_False/Câu 2.png"]
    assert result.notification == "Đã bổ sung 1 câu True/False."
    report = AnswerKeyRepository().load(subject.path, subject.questions)
    assert report.answers == {
        "Selections_1_choose/Câu 1.png": "A",
        "True_False/Câu 2.png": "B",
    }
    assert database.latest_bank_version(subject.name) == 2
    assert (subject_path / "answer_versions" / "answers.v1.csv").exists()
    assert (subject_path / "answer_versions" / "answers.v2.csv").exists()
    database.close()


def test_category_and_answer_update_regrades_every_historical_exam(
    tmp_path: Path,
) -> None:
    data = tmp_path / "DATA"
    subject_path = data / "TEST101"
    old_path = subject_path / "Selections_1_choose" / "Câu 186.png"
    make_image(old_path)
    write_answers(subject_path, [("Selections_1_choose/Câu 186.png", "A")])
    subject_v1 = scan_subject(data)
    database = Database(tmp_path / "progress.sqlite3")
    checker = bootstrap(database, subject_v1, lambda _question: "AD")

    service = ExamService(
        database,
        subject_v1.questions,
        {"Selections_1_choose/Câu 186.png": "A"},
    )
    session = service.create_session(
        ExamConfig(
            subject=subject_v1.name,
            categories=("Selections_1_choose",),
            question_count=1,
            duration_minutes=1,
            feedback_mode=FeedbackMode.DEFERRED,
        )
    )
    session.set_answer("A")
    attempt_id = session.submit().attempt_id
    old_question_id = subject_v1.questions[0].id

    new_path = subject_path / "Selections_Multiple_choose" / "Câu 186.png"
    new_path.parent.mkdir(parents=True)
    old_path.rename(new_path)
    subject_v2 = scan_subject(data)
    database.sync_questions(subject_v2.questions, [subject_v2.name])

    result = checker.check_subject(subject_v2)

    assert result.applied
    assert len(result.updated) == 1
    assert not result.added and not result.deleted
    assert "đáp án A sang Multiple Choice — đáp án AD" in result.notification
    detail = database.exam_detail(attempt_id)[0]
    assert detail["question_id"] == subject_v2.questions[0].id
    assert detail["question_id"] != old_question_id
    assert detail["relative_path"] == "Selections_Multiple_choose/Câu 186.png"
    assert detail["correct_answer"] == "AD"
    assert detail["is_correct"] == 0
    assert detail["awarded_score"] == 5.0
    attempt = database.exam_history(subject_v2.name)[0]
    assert attempt["score"] == 5.0
    assert attempt["score_percent"] == 50.0
    assert attempt["correct"] == 0
    assert attempt["bank_version"] == 1
    assert attempt["graded_bank_version"] == 2
    stats = database.question_error_stats([subject_v2.questions[0].id])
    assert stats[subject_v2.questions[0].id].total_attempts == 1
    assert stats[subject_v2.questions[0].id].wrong_count == 1
    revisions = database._connection.execute(
        """SELECT revision,active FROM question_revisions
        WHERE subject=? ORDER BY revision""",
        (subject_v2.name,),
    ).fetchall()
    assert [(row["revision"], row["active"]) for row in revisions] == [(1, 0), (2, 1)]
    database.close()


def test_delete_only_deactivates_question_and_preserves_exam_history(
    tmp_path: Path,
) -> None:
    data = tmp_path / "DATA"
    subject_path = data / "TEST101"
    first = subject_path / "Selections_1_choose" / "Câu 1.png"
    second = subject_path / "Selections_1_choose" / "Câu 2.png"
    make_image(first)
    make_image(second)
    write_answers(
        subject_path,
        [
            ("Selections_1_choose/Câu 1.png", "A"),
            ("Selections_1_choose/Câu 2.png", "B"),
        ],
    )
    subject_v1 = scan_subject(data)
    database = Database(tmp_path / "progress.sqlite3")
    checker = bootstrap(database, subject_v1)
    service = ExamService(
        database,
        subject_v1.questions,
        {
            "Selections_1_choose/Câu 1.png": "A",
            "Selections_1_choose/Câu 2.png": "B",
        },
    )
    session = service.create_session(
        ExamConfig(
            subject=subject_v1.name,
            categories=("Selections_1_choose",),
            question_count=2,
            duration_minutes=1,
            feedback_mode=FeedbackMode.DEFERRED,
        )
    )
    for index, item in enumerate(session.items):
        session.current_index = index
        session.set_answer(item.question.correct_answer)
    attempt_id = session.submit().attempt_id
    deleted_id = next(q.id for q in subject_v1.questions if q.absolute_path == second)

    second.unlink()
    subject_v2 = scan_subject(data)
    database.sync_questions(subject_v2.questions, [subject_v2.name])
    result = checker.check_subject(subject_v2)

    assert result.applied
    assert len(result.deleted) == 1
    assert result.notification == "Đã cập nhật bộ 1 câu ôn tập mới nhất."
    assert len(database.exam_detail(attempt_id)) == 2
    deleted = database._connection.execute(
        "SELECT active FROM questions WHERE id=?", (deleted_id,)
    ).fetchone()
    assert deleted["active"] == 0
    manifest = json.loads(
        (subject_path / "answer_versions" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["bank_version"] == 2
    assert len(manifest["questions"]) == 1
    report = AnswerKeyRepository().load(subject_v2.path, subject_v2.questions)
    assert list(report.answers) == ["Selections_1_choose/Câu 1.png"]
    database.close()


def test_pending_answers_are_applied_and_archived(tmp_path: Path) -> None:
    data = tmp_path / "DATA"
    subject_path = data / "TEST101"
    make_image(subject_path / "Selections_1_choose" / "Câu 1.png")
    write_answers(subject_path, [("Selections_1_choose/Câu 1.png", "A")])
    subject = scan_subject(data)
    database = Database(tmp_path / "progress.sqlite3")

    def no_ocr(_question) -> str:
        raise AssertionError("Không được OCR khi pending answer đã hợp lệ")

    checker = bootstrap(database, subject, no_ocr)
    make_image(subject_path / "True_False" / "Câu 2.png")
    with (subject_path / "answers.pending.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["image_name", "correct_answer"])
        writer.writerow(["True_False/Câu 2.png", "B"])
    subject = scan_subject(data)
    database.sync_questions(subject.questions, [subject.name])

    result = checker.check_subject(subject)

    assert result.applied and not result.errors
    assert not (subject_path / "answers.pending.csv").exists()
    assert (
        subject_path / "answer_versions" / "answers.pending.applied.v2.csv"
    ).exists()
    database.close()


def test_frequency_analyzer_uses_only_active_latest_revision(tmp_path: Path) -> None:
    data = tmp_path / "DATA"
    subject_path = data / "TEST101"
    old_path = subject_path / "Selections_1_choose" / "Câu 9.png"
    make_image(old_path)
    write_answers(subject_path, [("Selections_1_choose/Câu 9.png", "A")])
    subject = scan_subject(data)
    database = Database(tmp_path / "progress.sqlite3")
    checker = bootstrap(database, subject, lambda _question: "AD")
    new_path = subject_path / "Selections_Multiple_choose" / "Câu 9.png"
    new_path.parent.mkdir(parents=True)
    old_path.rename(new_path)
    subject = scan_subject(data)
    database.sync_questions(subject.questions, [subject.name])
    assert checker.check_subject(subject).applied

    rows = load_rows(database._connection, subject.name)

    assert len(rows) == 1
    assert rows[0]["question_id"] == subject.questions[0].id
    assert rows[0]["relative_path"] == "Selections_Multiple_choose/Câu 9.png"
    assert rows[0]["bank_version"] == 2
    database.close()
