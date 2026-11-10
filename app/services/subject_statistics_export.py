"""Export the same subject statistics used by the in-app review dashboard."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.config import CATEGORIES
from app.repositories.answer_key import AnswerKeyRepository
from app.repositories.database import Database
from app.services.adaptive import AdaptiveReviewService
from app.services.data_scanner import DataScannerService
from app.test_mode import is_trial_subject


def export_subject_statistics(
    database: Database,
    data_dir: Path,
    output_file: Path,
    *,
    test_mode: bool = False,
) -> Path:
    """Write a local JSON snapshot of the dashboard, never mixing data modes."""
    output_file = Path(output_file)
    if any(
        path.is_symlink()
        for path in (output_file, output_file.parent, output_file.parent.parent)
    ):
        raise ValueError(f"Đường dẫn báo cáo không an toàn: {output_file}")
    subjects = [
        subject
        for subject in DataScannerService(data_dir).scan()
        if is_trial_subject(subject.name) == test_mode
    ]
    if not subjects:
        label = "môn thử (_t)" if test_mode else "môn học"
        raise ValueError(f"Không tìm thấy {label} trong {data_dir}; chưa tạo báo cáo.")

    database.sync_questions(
        [question for subject in subjects for question in subject.questions],
        [subject.name for subject in subjects],
    )
    answer_repository = AnswerKeyRepository()
    subject_results: dict[str, object] = {}
    result: dict[str, object] = {
        "schema_version": 1,
        "mode": "test" if test_mode else "main",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "subjects": subject_results,
    }
    for subject in subjects:
        answer_report = answer_repository.load(subject.path, subject.questions)
        review = AdaptiveReviewService(
            database, subject.questions, answer_report.answers
        )
        learning = review.learning_by_category()
        errors = review.top_errors_by_category()
        categories = {}
        for category in CATEGORIES:
            categories[category] = {
                "question_count": subject.category_counts.get(category, 0),
                "not_learned": [
                    {
                        "question_id": item.question.id,
                        "image_name": item.question.relative_path,
                        "correct_answer": item.correct_answer,
                        "card_state": item.card_state,
                    }
                    for item in learning[category]
                ],
                "top_errors": [
                    {
                        "question_id": item.question.id,
                        "image_name": item.question.relative_path,
                        "correct_answer": item.correct_answer,
                        "wrong_count": item.wrong_count,
                        "total_attempts": item.total_attempts,
                        "error_rate": item.error_rate,
                    }
                    for item in errors[category]
                ],
            }
        subject_results[subject.name] = {
            "question_count": subject.question_count,
            "card_stats": database.card_stats(subject.name),
            "answer_key": {
                "file_found": answer_report.file_found,
                "valid_count": answer_report.valid_count,
                "missing_count": len(answer_report.missing),
                "invalid_count": len(answer_report.invalid),
            },
            "categories": categories,
        }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output_file.parent,
            prefix=".subject-statistics-", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(result, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
        os.replace(temporary_path, output_file)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return output_file
