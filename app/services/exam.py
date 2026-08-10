from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from app.domain.models import (
    ExamConfig,
    ExamQuestion,
    Question,
    QuestionErrorStat,
    normalize_answer,
)
from app.repositories.answer_key import AnswerKeyRepository, normalize_relative_path
from app.repositories.database import Database
from app.services.exam_bank import ExamBankAllocator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ExamResult:
    attempt_id: int
    config: ExamConfig
    total: int
    correct: int
    unanswered: int
    score: float
    score_percent: float
    items: list[ExamQuestion]

    @property
    def passed(self) -> bool:
        return self.score >= 7.0

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


class ExamSession:
    def __init__(
        self,
        database: Database,
        config: ExamConfig,
        questions: Sequence[Question],
    ):
        self.database = database
        self.config = config
        self.items = [ExamQuestion(question=question) for question in questions]
        self.current_index = 0
        self.started_at = utc_now()
        self.submitted = False

    @property
    def current(self) -> ExamQuestion:
        return self.items[self.current_index]

    def set_answer(self, value: str) -> None:
        item = self.current
        if item.confirmed:
            return
        normalized = normalize_answer(value)
        if any(char not in item.question.options for char in normalized):
            raise ValueError("Đáp án chứa lựa chọn không hợp lệ.")
        item.selected_answer = normalized

    def confirm_current(self) -> bool:
        if not self.current.selected_answer:
            raise ValueError("Hãy chọn ít nhất một đáp án.")
        self.current.confirmed = True
        return self.current.is_correct

    def submit(self, reason: str = "user") -> ExamResult:
        if self.submitted:
            raise ValueError("Bài thi đã được nộp.")
        self.submitted = True
        total = len(self.items)
        question_value = 10.0 / total if total else 0.0
        raw_scores = [item.calculate_score(question_value) for item in self.items]
        for item, raw_score in zip(self.items, raw_scores, strict=True):
            item.awarded_score = round(raw_score, 2)
        score = round(sum(raw_scores), 2)
        records = []
        for item in self.items:
            records.append(
                {
                    "question_id": item.question.id,
                    "relative_path": item.question.relative_path,
                    "selected_answer": normalize_answer(item.selected_answer),
                    "correct_answer": normalize_answer(item.question.correct_answer),
                    "is_correct": item.is_correct,
                    "awarded_score": item.awarded_score,
                }
            )
        attempt_id = self.database.save_exam_attempt(
            subject=self.config.subject,
            config={
                "categories": list(self.config.categories),
                "question_count": self.config.question_count,
                "duration_minutes": self.config.duration_minutes,
                "feedback_mode": self.config.feedback_mode.value,
            },
            started_at=self.started_at,
            submit_reason=reason,
            score=score,
            answers=records,
        )
        correct = sum(item.is_correct for item in self.items)
        unanswered = sum(not item.selected_answer for item in self.items)
        return ExamResult(
            attempt_id=attempt_id,
            config=replace(self.config),
            total=total,
            correct=correct,
            unanswered=unanswered,
            score=score,
            score_percent=round(score * 10.0, 2),
            items=self.items,
        )


class ExamService:
    def __init__(
        self,
        database: Database,
        questions: Sequence[Question],
        answers: Mapping[str, str],
        rng: random.Random | None = None,
    ):
        self.database = database
        self.questions = list(questions)
        self.rng = rng or random.SystemRandom()
        self.bank_allocator = ExamBankAllocator(self.rng)
        self.answers = {
            normalize_relative_path(path): normalize_answer(answer)
            for path, answer in answers.items()
        }

    def eligible_questions(self, categories: Sequence[str]) -> list[Question]:
        selected = set(categories)
        result: list[Question] = []
        for question in self.questions:
            relative = normalize_relative_path(question.relative_path)
            answer = self.answers.get(relative, "")
            if (
                question.category in selected
                and question.absolute_path.exists()
                and AnswerKeyRepository.validate(question, answer)
            ):
                result.append(replace(question, correct_answer=answer))
        return result

    @staticmethod
    def question_weight(stat: QuestionErrorStat) -> float:
        return ExamBankAllocator.error_weight(stat)

    def create_session(self, config: ExamConfig) -> ExamSession:
        if config.question_count <= 0:
            raise ValueError("Số câu hỏi phải lớn hơn 0.")
        if config.duration_minutes <= 0:
            raise ValueError("Thời gian phải lớn hơn 0 phút.")
        if not config.categories:
            raise ValueError("Hãy chọn ít nhất một loại câu hỏi.")
        pool = self.eligible_questions(config.categories)
        if config.question_count > len(pool):
            raise ValueError(
                f"Chỉ có {len(pool)} câu đủ đáp án trong các loại đã chọn."
            )
        stats = self.database.question_error_stats(
            [question.id for question in pool]
        )
        exposure_counts = self.database.question_exam_exposure_counts(
            [question.id for question in pool]
        )
        selected = self.bank_allocator.select(
            pool,
            config.question_count,
            stats,
            exposure_counts,
        )
        return ExamSession(self.database, config, selected)
