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
class LearningQuestionReview:
    question: Question
    correct_answer: str
    card_state: str = "learning"


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
        return score_answer(
            self.selected_answer,
            self.question.correct_answer,
            self.question.is_multiple,
            1.0,
        )[0]

    def calculate_score(self, question_value: float) -> float:
        """Calculate raw points using exact or partial-credit grading."""
        return score_answer(
            self.selected_answer,
            self.question.correct_answer,
            self.question.is_multiple,
            question_value,
        )[1]


def score_answer(
    selected_answer: str, correct_answer: str, is_multiple: bool, value: float
) -> tuple[bool, float]:
    """Return (exact match, points); multiple-choice gets partial credit."""
    selected = set(normalize_answer(selected_answer))
    correct = set(normalize_answer(correct_answer))
    exact = bool(correct) and selected == correct
    if not selected or not correct:
        return exact, 0.0
    if not is_multiple:
        return exact, value if exact else 0.0
    raw = (len(selected & correct) - len(selected - correct)) * (value / len(correct))
    return exact, max(0.0, min(value, raw))


def normalize_answer(value: str) -> str:
    """Return unique A-H characters in canonical order."""
    valid_options = "ABCDEFGH"
    text = (value or "").upper()
    if any(c.isalpha() and c not in valid_options for c in text):
        return ""  # words like "Because" are not answers
    chars = set(text)
    return "".join(char for char in valid_options if char in chars)
