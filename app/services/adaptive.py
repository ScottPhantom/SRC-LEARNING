from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.config import CATEGORIES
from app.domain.models import (
    LearningQuestionReview,
    Question,
    WeakQuestionReview,
    normalize_answer,
)
from app.repositories.database import Database


class AdaptiveReviewService:
    """Chuẩn bị dữ liệu thống kê ôn tập, độc lập hoàn toàn với PyQt5."""

    def __init__(
        self,
        database: Database,
        questions: Sequence[Question],
        answers: Mapping[str, str],
    ):
        self.database = database
        self.questions = list(questions)
        self.answers = dict(answers)

    def learning_by_category(self) -> dict[str, list[LearningQuestionReview]]:
        """Trả về câu mới và Chưa thuộc, giữ nguyên thứ tự file đã quét."""
        result: dict[str, list[LearningQuestionReview]] = {
            category: [] for category in CATEGORIES
        }
        unlearned_states = self.database.unlearned_question_states(
            self.questions[0].subject if self.questions else ""
        )
        for question in self.questions:
            card_state = unlearned_states.get(question.id)
            if card_state is None:
                continue
            result.setdefault(question.category, []).append(
                LearningQuestionReview(
                    question=question,
                    correct_answer=normalize_answer(
                        self.answers.get(question.relative_path, "")
                    ),
                    card_state=card_state,
                )
            )
        return result

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
