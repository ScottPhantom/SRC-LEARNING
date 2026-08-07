from __future__ import annotations

import csv
import logging
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app.config import MULTIPLE_CATEGORY, TRUE_FALSE_CATEGORY
from app.domain.models import Question, normalize_answer

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AnswerKeyReport:
    csv_path: Path | None = None
    file_found: bool = False
    total_rows: int = 0
    answers: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    unknown_paths: list[str] = field(default_factory=list)

    @property
    def valid_count(self) -> int:
        return len(self.answers)


def normalize_relative_path(value: str) -> str:
    text = unicodedata.normalize(
        "NFC", value.strip().strip('"\'').replace("\\", "/")
    )
    return PurePosixPath(text).as_posix().lstrip("./")


class AnswerKeyRepository:
    FILE_NAME = "answers.csv"

    def load(self, subject_path: Path, questions: list[Question]) -> AnswerKeyReport:
        subject_path = Path(subject_path).expanduser().resolve()
        csv_path = (subject_path / self.FILE_NAME).resolve()
        report = AnswerKeyReport(csv_path=csv_path)
        by_path = {normalize_relative_path(q.relative_path): q for q in questions}
        LOGGER.info(
            "Đang đọc answer key: path=%s, subject=%s, scanned_questions=%d",
            csv_path,
            subject_path.name,
            len(by_path),
        )
        if not csv_path.exists():
            report.missing = sorted(by_path)
            LOGGER.warning(
                "Không tìm thấy answers.csv tại %s; mapped=0, missing=%d",
                csv_path,
                len(report.missing),
            )
            return report
        report.file_found = True

        casefold_paths: dict[str, list[str]] = {}
        basename_paths: dict[str, list[str]] = {}
        for relative in by_path:
            casefold_paths.setdefault(relative.casefold(), []).append(relative)
            basename_paths.setdefault(PurePosixPath(relative).name.casefold(), []).append(relative)

        seen: set[str] = set()
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                normalized_headers = [
                    (header or "").strip().casefold() for header in (reader.fieldnames or [])
                ]
                if normalized_headers != ["image_name", "correct_answer"]:
                    reason = (
                        "answers.csv phải có đúng hai cột image_name,correct_answer; "
                        f"thực tế={reader.fieldnames}"
                    )
                    report.invalid.append(reason)
                    report.missing = sorted(by_path)
                    LOGGER.warning("Từ chối answer key %s: %s", csv_path, reason)
                    return report
                for line_number, row in enumerate(reader, start=2):
                    report.total_rows += 1
                    # DictReader retains original header whitespace/case; access by position.
                    values = list(row.values())
                    raw_image_name = str(values[0] or "") if values else ""
                    raw_answer = str(values[1] or "") if len(values) > 1 else ""
                    input_path = normalize_relative_path(raw_image_name)
                    if not input_path:
                        reason = f"Dòng {line_number}: thiếu image_name"
                        report.invalid.append(reason)
                        LOGGER.warning("Reject %s: %s", csv_path, reason)
                        continue

                    relative, match_method = self._match_question_path(
                        input_path,
                        subject_path.name,
                        by_path,
                        casefold_paths,
                        basename_paths,
                    )
                    if relative is None:
                        report.unknown_paths.append(input_path)
                        LOGGER.warning(
                            "Reject dòng %d: image_name=%r normalized=%r không khớp "
                            "Question.relative_path nào",
                            line_number,
                            raw_image_name,
                            input_path,
                        )
                        continue
                    if relative in seen:
                        report.duplicates.append(relative)
                        LOGGER.warning(
                            "Reject dòng %d: image_name=%r trùng với dòng trước (canonical=%s)",
                            line_number,
                            raw_image_name,
                            relative,
                        )
                        continue
                    seen.add(relative)
                    question = by_path[relative]
                    answer = normalize_answer(raw_answer)
                    if not self.validate(question, answer):
                        report.invalid.append(relative)
                        LOGGER.warning(
                            "Reject dòng %d: image_name=%r map=%s, correct_answer=%r "
                            "không hợp lệ cho category=%s",
                            line_number,
                            raw_image_name,
                            relative,
                            raw_answer,
                            question.category,
                        )
                        continue
                    report.answers[relative] = answer
                    if match_method != "exact":
                        LOGGER.info(
                            "Map dòng %d bằng %s: %r -> %s",
                            line_number,
                            match_method,
                            raw_image_name,
                            relative,
                        )
        except (OSError, csv.Error, UnicodeError) as exc:
            report.invalid.append(f"Không đọc được answers.csv: {exc}")
            report.missing = sorted(by_path)
            LOGGER.exception("Không đọc được answer key %s", csv_path)
            return report

        report.missing = sorted(set(by_path) - set(report.answers))
        rejected = report.total_rows - report.valid_count
        LOGGER.info(
            "Kết quả answers.csv: total_rows=%d, mapped=%d, rejected=%d, "
            "missing_questions=%d, duplicates=%d, unknown_paths=%d",
            report.total_rows,
            report.valid_count,
            rejected,
            len(report.missing),
            len(report.duplicates),
            len(report.unknown_paths),
        )
        return report

    @staticmethod
    def _match_question_path(
        input_path: str,
        subject_name: str,
        by_path: dict[str, Question],
        casefold_paths: dict[str, list[str]],
        basename_paths: dict[str, list[str]],
    ) -> tuple[str | None, str]:
        if input_path in by_path:
            return input_path, "exact"

        parts = PurePosixPath(input_path).parts
        if parts and parts[0].casefold() == subject_name.casefold():
            without_subject = PurePosixPath(*parts[1:]).as_posix()
            if without_subject in by_path:
                return without_subject, "subject-prefix"

        insensitive = casefold_paths.get(input_path.casefold(), [])
        if len(insensitive) == 1:
            return insensitive[0], "case-insensitive"

        # Compatibility for legacy CSV files containing only the filename.
        # It is accepted only when the basename is unique inside the subject.
        basename = PurePosixPath(input_path).name.casefold()
        basename_matches = basename_paths.get(basename, [])
        if len(basename_matches) == 1:
            return basename_matches[0], "unique-basename"
        return None, "unmatched"

    @staticmethod
    def validate(question: Question, answer: str) -> bool:
        normalized = normalize_answer(answer)
        if not normalized:
            return False
        if question.category == MULTIPLE_CATEGORY:
            return 2 <= len(normalized) <= len(question.options) and all(
                option in question.options for option in normalized
            )
        if question.category == TRUE_FALSE_CATEGORY:
            return len(normalized) == 1 and normalized in question.options
        return len(normalized) == 1 and normalized in question.options
