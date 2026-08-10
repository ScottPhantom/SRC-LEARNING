from __future__ import annotations

import random
from collections import Counter
from pathlib import Path

import pytest

from app.domain.models import Question, QuestionErrorStat
from app.services.exam_bank import ExamBankAllocator


def make_bank(category_counts: dict[str, int]) -> list[Question]:
    questions: list[Question] = []
    for category, amount in category_counts.items():
        for index in range(amount):
            question_id = f"{category}-{index}"
            questions.append(
                Question(
                    id=question_id,
                    subject="TEST101",
                    category=category,
                    relative_path=f"{category}/{question_id}.png",
                    absolute_path=Path(f"/{question_id}.png"),
                )
            )
    return questions


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (
            10,
            {
                "Fill_blanks": 1,
                "Selections_1_choose": 7,
                "Selections_Multiple_choose": 1,
                "True_False": 1,
            },
        ),
        (
            50,
            {
                "Fill_blanks": 6,
                "Selections_1_choose": 34,
                "Selections_Multiple_choose": 6,
                "True_False": 4,
            },
        ),
        (
            289,
            {
                "Fill_blanks": 37,
                "Selections_1_choose": 194,
                "Selections_Multiple_choose": 37,
                "True_False": 21,
            },
        ),
    ],
)
def test_category_allocation_matches_ite303c_bank(
    amount: int, expected: dict[str, int]
) -> None:
    counts = {
        "Fill_blanks": 37,
        "Selections_1_choose": 194,
        "Selections_Multiple_choose": 37,
        "True_False": 21,
    }

    plan = ExamBankAllocator.allocation_plan_from_counts(counts, amount)

    assert {item.category: item.quota for item in plan} == expected
    assert sum(item.quota for item in plan) == amount
    assert sum(item.share for item in plan) == pytest.approx(1.0)
    assert next(
        item.strategy for item in plan if item.category == "Selections_1_choose"
    ) == "coverage"


def test_small_exam_protects_categories_when_seats_allow() -> None:
    counts = {"dominant": 90, "minor-a": 4, "minor-b": 3, "minor-c": 3}

    four_seats = ExamBankAllocator.allocation_plan_from_counts(counts, 4)
    one_seat = ExamBankAllocator.allocation_plan_from_counts(counts, 1)

    assert {item.category: item.quota for item in four_seats} == {
        "dominant": 1,
        "minor-a": 1,
        "minor-b": 1,
        "minor-c": 1,
    }
    assert {item.category: item.quota for item in one_seat} == {
        "dominant": 1,
        "minor-a": 0,
        "minor-b": 0,
        "minor-c": 0,
    }


def test_minority_uses_error_review_and_dominant_uses_coverage() -> None:
    questions = make_bank({"majority": 10, "minority": 5})
    majority = [question for question in questions if question.category == "majority"]
    minority = [question for question in questions if question.category == "minority"]
    stats = {
        question.id: QuestionErrorStat(
            question.id,
            total_attempts=5,
            wrong_count=4,
        )
        for question in minority[:3]
    }
    exposure_counts = {
        question.id: (0 if question in majority[:4] else 8)
        for question in questions
    }
    allocator = ExamBankAllocator(random.Random(2026))

    selected = allocator.select(questions, 6, stats, exposure_counts)
    selected_counts = Counter(question.category for question in selected)
    selected_majority = {question.id for question in selected if question.category == "majority"}
    selected_minority = {question.id for question in selected if question.category == "minority"}

    assert selected_counts == {"majority": 4, "minority": 2}
    assert selected_majority == {question.id for question in majority[:4]}
    assert len(selected_minority) == 2
    assert len({question.id for question in selected}) == 6


def test_minority_error_review_converges_to_forty_percent() -> None:
    questions = make_bank({"majority": 10, "minority": 5})
    error_question = next(
        question
        for question in questions
        if question.category == "minority"
    )
    stats = {
        error_question.id: QuestionErrorStat(
            error_question.id,
            total_attempts=10,
            wrong_count=8,
        )
    }
    allocator = ExamBankAllocator(random.Random(2026))
    error_selections = 0
    minority_selections = 0

    for _ in range(1_000):
        selected = allocator.select(questions, 6, stats, {})
        error_selections += sum(question.id == error_question.id for question in selected)
        minority_selections += sum(
            question.category == "minority" for question in selected
        )

    assert minority_selections == 2_000
    assert error_selections / minority_selections == pytest.approx(0.40, abs=0.03)


def test_repeated_exams_cover_the_dominant_category() -> None:
    questions = make_bank(
        {
            "Fill_blanks": 37,
            "Selections_1_choose": 194,
            "Selections_Multiple_choose": 37,
            "True_False": 21,
        }
    )
    allocator = ExamBankAllocator(random.Random(2026))
    exposure_counts = {question.id: 0 for question in questions}
    dominant_ids = {
        question.id
        for question in questions
        if question.category == "Selections_1_choose"
    }

    for _ in range(28):
        selected = allocator.select(questions, 10, {}, exposure_counts)
        assert Counter(question.category for question in selected) == {
            "Fill_blanks": 1,
            "Selections_1_choose": 7,
            "Selections_Multiple_choose": 1,
            "True_False": 1,
        }
        for question in selected:
            exposure_counts[question.id] += 1

    assert all(exposure_counts[question_id] >= 1 for question_id in dominant_ids)


def test_allocation_rejects_invalid_amounts() -> None:
    with pytest.raises(ValueError, match="lớn hơn 0"):
        ExamBankAllocator.allocation_plan_from_counts({"single": 3}, 0)
    with pytest.raises(ValueError, match="Chỉ có 3"):
        ExamBankAllocator.allocation_plan_from_counts({"single": 3}, 4)
    with pytest.raises(ValueError, match="không có câu hỏi"):
        ExamBankAllocator.allocation_plan_from_counts({}, 1)
