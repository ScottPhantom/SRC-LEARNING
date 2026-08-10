from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.domain.models import Question, QuestionErrorStat


@dataclass(slots=True, frozen=True)
class CategoryAllocation:
    category: str
    pool_count: int
    share: float
    raw_quota: float
    quota: int
    strategy: str


class ExamBankAllocator:
    """Pure question-bank allocator; database and UI concerns stay outside it."""

    MINORITY_ERROR_SHARE = 0.40

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.SystemRandom()

    @staticmethod
    def _dominant_category(category_counts: Mapping[str, int]) -> str:
        return min(category_counts, key=lambda name: (-category_counts[name], name))

    @classmethod
    def allocation_plan_from_counts(
        cls, category_counts: Mapping[str, int], amount: int
    ) -> list[CategoryAllocation]:
        """Apportion exactly ``amount`` seats while protecting small categories.

        Quotas start from proportional floors. When the exam has at least one
        seat per category, every non-empty category receives a minimum of one.
        Remaining seats go to the category furthest below its raw proportional
        quota. This is a constrained largest-remainder allocation: unlike
        independently rounding every category, its quotas always sum to amount.
        """
        counts = {name: int(count) for name, count in category_counts.items() if count > 0}
        total = sum(counts.values())
        if not counts:
            raise ValueError("Ngân hàng đề không có câu hỏi.")
        if amount <= 0:
            raise ValueError("Số câu hỏi phải lớn hơn 0.")
        if amount > total:
            raise ValueError(f"Chỉ có {total} câu trong ngân hàng đề.")

        dominant = cls._dominant_category(counts)
        raw = {name: amount * count / total for name, count in counts.items()}
        quotas = {name: min(counts[name], math.floor(raw[name])) for name in counts}
        lower_bound = 1 if amount >= len(counts) else 0
        if lower_bound:
            for name, quota in quotas.items():
                quotas[name] = max(lower_bound, quota)

        while sum(quotas.values()) > amount:
            donors = [
                name
                for name in quotas
                if quotas[name] > lower_bound
            ]
            donor = max(
                donors,
                key=lambda name: (
                    quotas[name] - raw[name],
                    quotas[name],
                    name == dominant,
                    name,
                ),
            )
            quotas[donor] -= 1

        while sum(quotas.values()) < amount:
            candidates = [name for name in quotas if quotas[name] < counts[name]]
            recipient = max(
                candidates,
                key=lambda name: (
                    raw[name] - quotas[name],
                    name != dominant,
                    counts[name],
                    name,
                ),
            )
            quotas[recipient] += 1

        return [
            CategoryAllocation(
                category=name,
                pool_count=counts[name],
                share=counts[name] / total,
                raw_quota=raw[name],
                quota=quotas[name],
                strategy="coverage" if name == dominant else "minority_40_60",
            )
            for name in sorted(counts)
        ]

    @classmethod
    def allocation_plan(
        cls, questions: Sequence[Question], amount: int
    ) -> list[CategoryAllocation]:
        counts: dict[str, int] = defaultdict(int)
        for question in questions:
            counts[question.category] += 1
        return cls.allocation_plan_from_counts(counts, amount)

    @staticmethod
    def error_weight(stat: QuestionErrorStat) -> float:
        """Keep the existing adaptive score as the minority-review preference."""
        base = {"known": 0.45, "learning": 1.15}.get(stat.card_state, 1.0)
        error_boost = 5.0 * stat.error_rate
        repeated_error_boost = min(4.0, 0.5 * stat.wrong_count)
        correct_count = max(0, stat.total_attempts - stat.wrong_count)
        mastery_discount = min(0.65, 0.04 * correct_count)
        return max(0.1, base + error_boost + repeated_error_boost - mastery_discount)

    def _weighted_sample(
        self,
        questions: Sequence[Question],
        weights: Sequence[float],
        amount: int,
    ) -> list[Question]:
        available = list(zip(questions, weights, strict=True))
        selected: list[Question] = []
        while available and len(selected) < amount:
            total_weight = sum(weight for _, weight in available)
            threshold = self.rng.random() * total_weight
            cumulative = 0.0
            chosen_index = len(available) - 1
            for index, (_question, weight) in enumerate(available):
                cumulative += weight
                if threshold < cumulative:
                    chosen_index = index
                    break
            question, _weight = available.pop(chosen_index)
            selected.append(question)
        return selected

    def _least_exposed_sample(
        self,
        questions: Sequence[Question],
        exposure_counts: Mapping[str, int],
        amount: int,
    ) -> list[Question]:
        available = list(questions)
        selected: list[Question] = []
        while available and len(selected) < amount:
            minimum = min(exposure_counts.get(question.id, 0) for question in available)
            tier = [
                question
                for question in available
                if exposure_counts.get(question.id, 0) == minimum
            ]
            chosen = self.rng.choice(tier)
            available.remove(chosen)
            selected.append(chosen)
        return selected

    def _minority_sample(
        self,
        questions: Sequence[Question],
        stats: Mapping[str, QuestionErrorStat],
        amount: int,
    ) -> list[Question]:
        error_candidates = [
            question
            for question in questions
            if stats.get(question.id, QuestionErrorStat(question.id)).wrong_count > 0
        ]
        target = amount * self.MINORITY_ERROR_SHARE
        review_amount = math.floor(target)
        if self.rng.random() < target - review_amount:
            review_amount += 1
        review_amount = min(
            len(error_candidates),
            amount,
            review_amount,
        )
        selected = self._weighted_sample(
            error_candidates,
            [
                self.error_weight(stats.get(question.id, QuestionErrorStat(question.id)))
                for question in error_candidates
            ],
            review_amount,
        )
        selected_ids = {question.id for question in selected}
        error_ids = {question.id for question in error_candidates}
        random_pool = [
            question for question in questions if question.id not in error_ids
        ]
        random_amount = min(len(random_pool), amount - len(selected))
        selected.extend(self.rng.sample(random_pool, random_amount))
        selected_ids = {question.id for question in selected}
        if len(selected) < amount:
            overflow_pool = [
                question for question in questions if question.id not in selected_ids
            ]
            selected.extend(self.rng.sample(overflow_pool, amount - len(selected)))
        return selected

    def select(
        self,
        questions: Sequence[Question],
        amount: int,
        stats: Mapping[str, QuestionErrorStat],
        exposure_counts: Mapping[str, int],
    ) -> list[Question]:
        groups: dict[str, list[Question]] = defaultdict(list)
        for question in questions:
            groups[question.category].append(question)

        selected: list[Question] = []
        for allocation in self.allocation_plan(questions, amount):
            group = groups[allocation.category]
            if allocation.strategy == "coverage":
                selected.extend(
                    self._least_exposed_sample(group, exposure_counts, allocation.quota)
                )
            else:
                selected.extend(self._minority_sample(group, stats, allocation.quota))
        self.rng.shuffle(selected)
        return selected
