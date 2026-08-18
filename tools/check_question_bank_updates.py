"""Kiểm tra và áp dụng version mới của answer bank theo thay đổi trong DATA."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import pytesseract

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import DEFAULT_DB_PATH, DEFAULT_MASK_REGION, MULTIPLE_CATEGORY
from app.repositories.answer_key import AnswerKeyRepository
from app.repositories.database import Database
from app.services.answer_ocr import crop_answer, read_image_unicode, recognize
from app.services.data_scanner import DataScannerService
from app.services.question_bank_updates import QuestionBankUpdateChecker
from tools.build_answers import prompt_for_manual_answer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "DATA")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--subject", help="Chỉ kiểm tra một môn học")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Tạo bank version mới, cập nhật answers.csv và chấm lại lịch sử",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Không hỏi đáp án thủ công khi OCR thất bại",
    )
    return parser


def interactive_answer_resolver(question) -> str:
    """Try OCR first, then require a valid developer answer in an interactive CLI."""

    answer = ""
    try:
        image = read_image_unicode(question.absolute_path)
        crop = crop_answer(image, DEFAULT_MASK_REGION)
        answer = recognize(crop, question.category == MULTIPLE_CATEGORY)
    except (
        OSError,
        ValueError,
        RuntimeError,
        cv2.error,
        pytesseract.TesseractError,
    ) as exc:
        print(
            f"WARNING: OCR thất bại cho {question.relative_path}: {exc}",
            file=sys.stderr,
        )
    if AnswerKeyRepository.validate(question, answer):
        return answer
    return prompt_for_manual_answer(question)


def main() -> int:
    args = build_parser().parse_args()
    subjects = DataScannerService(args.data_dir).scan()
    if args.subject:
        subjects = [subject for subject in subjects if subject.name == args.subject]
        if not subjects:
            print(f"ERROR: Không tìm thấy môn học {args.subject}", file=sys.stderr)
            return 1
    database = Database(args.database)
    try:
        database.sync_questions(
            [question for subject in subjects for question in subject.questions],
            [subject.name for subject in subjects],
        )
        resolver = (
            interactive_answer_resolver
            if args.apply and not args.non_interactive and sys.stdin.isatty()
            else None
        )
        checker = QuestionBankUpdateChecker(
            database, DEFAULT_MASK_REGION, answer_resolver=resolver
        )
        results = checker.check(subjects, apply=args.apply)
    finally:
        database.close()

    failed = False
    for result in results:
        if result.errors:
            failed = True
            print(f"{result.subject}: ERROR")
            for error in result.errors:
                print(f"  - {error}")
            continue
        if not result.changes:
            suffix = " (đã khởi tạo manifest v1)" if result.initialized else ""
            print(f"{result.subject}: không có thay đổi{suffix}")
            continue
        mode = "đã áp dụng" if result.applied else "dry-run"
        print(
            f"{result.subject}: v{result.previous_version} -> v{result.bank_version} "
            f"[{mode}] ADD={len(result.added)} UPDATE={len(result.updated)} "
            f"DELETE={len(result.deleted)}"
        )
        if result.notification:
            print(result.notification)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
