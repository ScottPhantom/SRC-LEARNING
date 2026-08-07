from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.config import CATEGORIES
from app.domain.models import Question, WeakQuestionReview, normalize_answer
from app.repositories.database import Database


class AdaptiveReviewService:
    """Chuẩn bị dữ liệu góc yếu điểm, độc lập hoàn toàn với PyQt5."""

    def __init__(
        self,
        database: Database,
        questions: Sequence[Question],
        answers: Mapping[str, str],
    ):
        self.database = database
        self.questions = list(questions)
        self.answers = dict(answers)

    def top_errors_by_category(
        self, limit: int = 20
    ) -> dict[str, list[WeakQuestionReview]]:
        result: dict[str, list[WeakQuestionReview]] = {
            category: [] for category in CATEGORIES
        }
        stats = self.database.question_error_stats(
            [question.id for question in self.questions]
        )
        for question in self.questions:
            stat = stats.get(question.id)
            if stat is None or stat.total_attempts <= 0 or stat.wrong_count <= 0:
                continue
            result.setdefault(question.category, []).append(
                WeakQuestionReview(
                    question=question,
                    correct_answer=normalize_answer(
                        self.answers.get(question.relative_path, "")
                    ),
                    total_attempts=stat.total_attempts,
                    wrong_count=stat.wrong_count,
                )
            )
        for category, entries in result.items():
            entries.sort(
                key=lambda entry: (
                    -entry.error_rate,
                    -entry.wrong_count,
                    -entry.total_attempts,
                    entry.question.relative_path.casefold(),
                )
            )
            result[category] = entries[: max(0, limit)]
        return result
