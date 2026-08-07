from __future__ import annotations

import logging
import random
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from app.domain.models import Question, normalize_answer
from app.repositories.answer_key import AnswerKeyRepository, normalize_relative_path
from app.repositories.database import Database

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class FlashState:
    session_id: int
    position: int
    total: int
    question: Question | None
    completed: bool


class FlashcardService:
    def __init__(
        self,
        database: Database,
        questions: Sequence[Question],
        answers: Mapping[str, str] | None = None,
    ):
        self.database = database
        normalized_answers = {
            normalize_relative_path(path): normalize_answer(answer)
            for path, answer in (answers or {}).items()
        }
        enriched_questions: list[Question] = []
        for question in questions:
            answer = normalized_answers.get(
                normalize_relative_path(question.relative_path), ""
            )
            enriched_questions.append(
                replace(question, correct_answer=answer)
                if AnswerKeyRepository.validate(question, answer)
                else question
            )
        self.questions = {question.id: question for question in enriched_questions}
        self.subject = questions[0].subject if questions else ""
        self.session_id: int | None = None
        self.order: list[str] = []
        self.position = 0

    def stats(self) -> dict[str, int]:
        return self.database.card_stats(self.subject)

    def resume_or_start(self) -> FlashState:
        active = self.database.active_flash_session(self.subject)
        if active:
            self.session_id = int(active["id"])
            self.order = self.database.flash_question_ids(self.session_id)
            self.position = int(active["current_position"])
        else:
            self.start_new(False)
        return self.state()

    def start_new(self, only_learning: bool = False) -> FlashState:
        if only_learning:
            allowed = set(self.database.learning_question_ids(self.subject))
            question_ids = [qid for qid in self.questions if qid in allowed]
            if not question_ids:
                raise ValueError("Chưa có thẻ nào ở trạng thái Chưa thuộc.")
        else:
            question_ids = list(self.questions)
        if not question_ids:
            raise ValueError("Môn học chưa có câu hỏi hợp lệ.")
        random.SystemRandom().shuffle(question_ids)
        self.session_id = self.database.create_flash_session(
            self.subject, question_ids, only_learning
        )
        self.order = question_ids
        self.position = 0
        return self.state()

    def restart(self) -> FlashState:
        """Xóa phiên active, xáo trộn toàn bộ thẻ và trở về câu đầu."""
        self.database.delete_active_flash_session(self.subject)
        self.session_id = None
        self.order = []
        self.position = 0
        return self.start_new(False)

    def state(self) -> FlashState:
        while self.position < len(self.order) and self.order[self.position] not in self.questions:
            self.position += 1
        completed = self.position >= len(self.order)
        if self.session_id is not None and completed:
            self.database.update_flash_position(self.session_id, self.position, True)
        question = None if completed else self.questions[self.order[self.position]]
        return FlashState(
            session_id=self.session_id or 0,
            position=self.position,
            total=len(self.order),
            question=question,
            completed=completed,
        )

    def rate_current(self, known: bool) -> FlashState:
        state = self.state()
        if state.completed or state.question is None or self.session_id is None:
            return state
        self.database.rate_card(state.question.id, known)
        self.position += 1
        completed = self.position >= len(self.order)
        self.database.update_flash_position(self.session_id, self.position, completed)
        return self.state()


@dataclass(slots=True)
class CramState:
    cycle_id: int
    question: Question | None
    current_round: int
    total_rounds: int
    remaining: int
    round_total: int
    round_mastered: int
    mastered: int
    wrong: int
    completed: bool


@dataclass(slots=True)
class CramRoundItem:
    question: Question
    mastered: bool
    wrong_count: int


class CrammingService:
    ROUND_SIZE = 10

    def __init__(
        self,
        database: Database,
        questions: Sequence[Question],
        answers: Mapping[str, str] | None = None,
    ):
        self.database = database
        self.subject = questions[0].subject if questions else ""
        self.grading_mode = "self_assessment" if answers is None else "answer_key_v1"
        if answers is None:
            eligible = list(questions)
        else:
            normalized_answers = {
                normalize_relative_path(path): normalize_answer(answer)
                for path, answer in answers.items()
            }
            eligible = []
            for question in questions:
                answer = normalized_answers.get(
                    normalize_relative_path(question.relative_path), ""
                )
                if AnswerKeyRepository.validate(question, answer):
                    eligible.append(replace(question, correct_answer=answer))
        self.questions = {question.id: question for question in eligible}
        self.cycle_id: int | None = None

    @staticmethod
    def build_rounds(question_ids: Sequence[str], seed: int) -> list[list[str]]:
        order = list(question_ids)
        random.Random(seed).shuffle(order)
        return [
            order[index : index + CrammingService.ROUND_SIZE]
            for index in range(0, len(order), CrammingService.ROUND_SIZE)
        ]

    @staticmethod
    def is_answer_correct(question: Question, selected_answer: str) -> bool:
        """Chấm exact match; câu nhiều đáp án không có điểm từng phần."""
        selected = set(normalize_answer(selected_answer))
        correct = set(normalize_answer(question.correct_answer))
        if not selected or not correct:
            return False
        if question.is_multiple:
            return selected == correct
        return normalize_answer(selected_answer) == normalize_answer(
            question.correct_answer
        )

    def resume_or_start(self) -> CramState:
        active = self.database.active_cram_cycle(self.subject)
        if active:
            active_id = int(active["id"])
            snapshot = set(self.database.cram_cycle_question_ids(active_id))
            if (
                snapshot == set(self.questions)
                and str(active["grading_mode"]) == self.grading_mode
            ):
                self.cycle_id = active_id
            else:
                LOGGER.info(
                    "Tạo lại chu kỳ Cramming vì answer key/question pool đã thay đổi"
                )
                self.start_new()
        else:
            latest = self.database.latest_cram_cycle(self.subject)
            if latest and latest["status"] == "completed":
                self.cycle_id = int(latest["id"])
            else:
                self.start_new()
        return self.state()

    def start_new(self) -> CramState:
        if not self.questions:
            raise ValueError("Môn học chưa có câu hỏi hợp lệ.")
        seed = secrets.randbelow(2_147_483_647)
        rounds = self.build_rounds(list(self.questions), seed)
        self.cycle_id = self.database.create_cram_cycle(
            self.subject, seed, rounds, self.grading_mode
        )
        return self.state()

    def state(self) -> CramState:
        if self.cycle_id is None:
            return CramState(
                cycle_id=0,
                question=None,
                current_round=0,
                total_rounds=0,
                remaining=0,
                round_total=0,
                round_mastered=0,
                mastered=0,
                wrong=0,
                completed=True,
            )
        stats = self.database.cram_stats(self.cycle_id)
        if not stats or stats.get("status") == "completed":
            return CramState(
                cycle_id=self.cycle_id,
                question=None,
                current_round=int(stats.get("current_round", 0)),
                total_rounds=int(stats.get("total_rounds", 0)),
                remaining=0,
                round_total=int(stats.get("round_total", 0)),
                round_mastered=int(stats.get("round_mastered", 0)),
                mastered=int(stats.get("mastered", 0)),
                wrong=int(stats.get("wrong", 0)),
                completed=True,
            )
        item = self.database.cram_current_item(self.cycle_id)
        # Files removed after the snapshot are completed as unavailable so the
        # cycle can always make progress.
        while item is not None and str(item["question_id"]) not in self.questions:
            LOGGER.warning(
                "Bỏ qua câu không còn tồn tại trong chu kỳ %s: %s",
                self.cycle_id,
                item["question_id"],
            )
            self.database.rate_cram_item(self.cycle_id, str(item["question_id"]), True)
            stats = self.database.cram_stats(self.cycle_id)
            item = self.database.cram_current_item(self.cycle_id)
        if not stats or stats.get("status") == "completed" or item is None:
            return (
                self.state()
                if stats.get("status") != "completed"
                else CramState(
                    cycle_id=self.cycle_id,
                    question=None,
                    current_round=int(stats.get("current_round", 0)),
                    total_rounds=int(stats.get("total_rounds", 0)),
                    remaining=0,
                    round_total=int(stats.get("round_total", 0)),
                    round_mastered=int(stats.get("round_mastered", 0)),
                    mastered=int(stats.get("mastered", 0)),
                    wrong=int(stats.get("wrong", 0)),
                    completed=True,
                )
            )
        return CramState(
            cycle_id=self.cycle_id,
            question=self.questions[str(item["question_id"])],
            current_round=int(stats["current_round"]),
            total_rounds=int(stats["total_rounds"]),
            remaining=int(stats["remaining"]),
            round_total=int(stats["round_total"]),
            round_mastered=int(stats["round_mastered"]),
            mastered=int(stats["mastered"]),
            wrong=int(stats["wrong"]),
            completed=False,
        )

    def rate_current(self, correct: bool) -> CramState:
        state = self.state()
        if state.completed or state.question is None or self.cycle_id is None:
            return state
        self.database.rate_cram_item(self.cycle_id, state.question.id, correct)
        return self.state()

    def current_round_items(self) -> list[CramRoundItem]:
        if self.cycle_id is None:
            return []
        result: list[CramRoundItem] = []
        for row in self.database.cram_round_items(self.cycle_id):
            question = self.questions.get(str(row["question_id"]))
            if question is not None:
                result.append(
                    CramRoundItem(
                        question=question,
                        mastered=bool(row["mastered"]),
                        wrong_count=int(row["wrong_count"]),
                    )
                )
        return result

    def focus_question(self, question_id: str) -> CramState:
        if self.cycle_id is None:
            return self.state()
        self.database.focus_cram_item(self.cycle_id, question_id)
        return self.state()
