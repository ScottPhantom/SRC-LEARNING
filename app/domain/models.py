from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class FeedbackMode(str, Enum):
    IMMEDIATE = "immediate"
    DEFERRED = "deferred"


@dataclass(slots=True)
class Question:
    id: str
    subject: str
    category: str
    relative_path: str
    absolute_path: Path
    correct_answer: str = ""
    option_letters: tuple[str, ...] = ()

    @property
    def is_multiple(self) -> bool:
        return self.category == "Selections_Multiple_choose"

    @property
    def options(self) -> tuple[str, ...]:
        if self.option_letters:
            return self.option_letters
        if self.category == "True_False":
            return ("A", "B")
        return ("A", "B", "C", "D")


@dataclass(slots=True)
class Subject:
    name: str
    path: Path
    questions: list[Question] = field(default_factory=list)
    invalid_images: list[str] = field(default_factory=list)

    @property
    def question_count(self) -> int:
        return len(self.questions)

    @property
    def category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for question in self.questions:
            counts[question.category] = counts.get(question.category, 0) + 1
        return counts

    def questions_in(self, categories: Iterable[str]) -> list[Question]:
        selected = set(categories)
        return [q for q in self.questions if q.category in selected]


@dataclass(slots=True)
class AppSettings:
    theme: str = "system"
    data_dir: str = "DATA"
    mask_x: float = 0.0
    mask_y: float = 0.90
    mask_width: float = 0.25
    mask_height: float = 0.10

    @property
    def crop_region(self) -> tuple[float, float, float, float]:
        return (self.mask_x, self.mask_y, self.mask_width, self.mask_height)

    @property
    def mask_region(self) -> tuple[float, float, float, float]:
        """Tên tương thích cho dữ liệu SQLite từ các phiên bản trước."""
        return self.crop_region


@dataclass(slots=True, frozen=True)
class QuestionErrorStat:
    question_id: str
    total_attempts: int = 0
    wrong_count: int = 0
    card_state: str = "new"

    @property
    def error_rate(self) -> float:
        if self.total_attempts <= 0:
            return 0.0
        return self.wrong_count / self.total_attempts


@dataclass(slots=True, frozen=True)
class WeakQuestionReview:
    question: Question
    correct_answer: str
    total_attempts: int
    wrong_count: int

    @property
    def error_rate(self) -> float:
        if self.total_attempts <= 0:
            return 0.0
        return self.wrong_count / self.total_attempts


@dataclass(slots=True)
class ExamConfig:
    subject: str
    categories: tuple[str, ...]
    question_count: int
    duration_minutes: int
    feedback_mode: FeedbackMode


@dataclass(slots=True)
class ExamQuestion:
    question: Question
    selected_answer: str = ""
    confirmed: bool = False
    awarded_score: float = 0.0

    @property
    def is_correct(self) -> bool:
        return normalize_answer(self.selected_answer) == normalize_answer(
            self.question.correct_answer
        )

    def calculate_score(self, question_value: float) -> float:
        """Calculate raw points using exact or partial-credit grading."""
        selected = set(normalize_answer(self.selected_answer))
        correct = set(normalize_answer(self.question.correct_answer))
        if not selected or not correct:
            return 0.0
        if not self.question.is_multiple:
            return question_value if selected == correct else 0.0
        correct_selected = len(selected & correct)
        wrong_selected = len(selected - correct)
        score = (correct_selected - wrong_selected) * (question_value / len(correct))
        return max(0.0, min(question_value, score))


def normalize_answer(value: str) -> str:
    """Return unique A-H characters in canonical order."""
    valid_options = "ABCDEFGH"
    chars = {char for char in (value or "").upper() if char in valid_options}
    return "".join(char for char in valid_options if char in chars)
