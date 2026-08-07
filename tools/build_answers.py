"""Tạo answers.csv từ vùng đáp án ở góc dưới-trái của ảnh."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np
import pytesseract

from app.config import MULTIPLE_CATEGORY
from app.domain.models import normalize_answer
from app.repositories.answer_key import (
    AnswerKeyRepository,
    normalize_relative_path,
)
from app.services.data_scanner import DataScannerService


def parse_region(value: str) -> tuple[float, float, float, float]:
    try:
        values = tuple(float(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Region phải gồm bốn số x,y,width,height") from exc
    if len(values) != 4:
        raise argparse.ArgumentTypeError("Region phải gồm bốn số x,y,width,height")
    x, y, width, height = values
    if min(values) < 0 or x + width > 1 or y + height > 1 or width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("Region phải nằm trong khoảng 0..1 của ảnh")
    return x, y, width, height


def read_image_unicode(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("OpenCV không đọc được ảnh")
    return image


def crop_answer(
    image: np.ndarray, region: tuple[float, float, float, float]
) -> np.ndarray:
    height, width = image.shape[:2]
    x, y, crop_width, crop_height = region
    x1, y1 = int(width * x), int(height * y)
    x2, y2 = max(x1 + 1, int(width * (x + crop_width))), max(
        y1 + 1, int(height * (y + crop_height))
    )
    return image[y1:y2, x1:x2]


def preprocess(crop: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]


def recognize(crop: np.ndarray, multiple: bool) -> str:
    """Nhận diện đáp án bằng nhiều biến thể, ưu tiên ảnh crop còn nguyên nét.

    Một số ảnh dùng chữ rất mảnh nên threshold Otsu có thể xóa hoàn toàn ký tự.
    Ngoài ra dữ liệu thực tế có cả chữ thường (ví dụ ``d``), vì vậy whitelist phải
    chứa cả hai kiểu chữ trước khi ``normalize_answer`` chuẩn hóa về A-D.
    """

    candidates = (crop, preprocess(crop))
    expected_lengths = range(2, 9) if multiple else (1,)
    for candidate in candidates:
        for psm in (7, 6, 10):
            raw = pytesseract.image_to_string(
                candidate,
                config=f"--psm {psm} -c tessedit_char_whitelist=ABCDEFGHabcdefgh",
            )
            answer = normalize_answer(raw)
            if len(answer) in expected_lengths:
                return answer
    return ""


def read_existing(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                relative = normalize_relative_path(row.get("image_name", ""))
                if relative:
                    result[relative] = normalize_answer(row.get("correct_answer", ""))
    except (OSError, csv.Error, UnicodeError) as exc:
        print(f"WARNING: Không đọc được {path}: {exc}", file=sys.stderr)
    return result


def write_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    temporary = path.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["image_name", "correct_answer"])
        writer.writerows(rows)
    temporary.replace(path)


def process_subject(subject, args: argparse.Namespace) -> tuple[int, int]:
    repository = AnswerKeyRepository()
    csv_path = subject.path / repository.FILE_NAME
    existing = read_existing(csv_path)
    output: list[tuple[str, str]] = []
    summary: Counter[str] = Counter()
    failed_dir = Path(args.failed_crops).resolve() / subject.name if args.failed_crops else None

    for question in subject.questions:
        relative = normalize_relative_path(question.relative_path)
        old_answer = existing.get(relative, "")
        if not args.overwrite and repository.validate(question, old_answer):
            output.append((relative, old_answer))
            summary["preserved"] += 1
            continue
        answer = ""
        crop = None
        try:
            image = read_image_unicode(question.absolute_path)
            crop = crop_answer(image, args.region)
            answer = recognize(crop, question.category == MULTIPLE_CATEGORY)
            if not repository.validate(question, answer):
                answer = ""
        except (OSError, ValueError, RuntimeError, cv2.error, pytesseract.TesseractError) as exc:
            print(f"WARNING: {subject.name}/{relative}: {exc}", file=sys.stderr)
        if answer:
            summary["recognized"] += 1
        else:
            summary["failed"] += 1
            print(
                f"WARNING: Không nhận diện được đáp án: {subject.name}/{relative}",
                file=sys.stderr,
            )
            if failed_dir is not None and crop is not None:
                destination = failed_dir / question.category
                destination.mkdir(parents=True, exist_ok=True)
                cv2.imencode(".png", crop)[1].tofile(str(destination / question.absolute_path.name))
        output.append((relative, answer))
    write_csv(csv_path, output)
    print(
        f"{subject.name}: {summary['recognized']} OCR thành công, "
        f"{summary['preserved']} giữ nguyên, {summary['failed']} cần điền thủ công -> {csv_path}"
    )
    return summary["recognized"] + summary["preserved"], summary["failed"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="DATA", help="Thư mục dữ liệu")
    parser.add_argument("--subject", help="Chỉ xử lý một môn học")
    parser.add_argument("--overwrite", action="store_true", help="OCR lại cả đáp án đã có")
    parser.add_argument(
        "--region",
        type=parse_region,
        default=(0.0, 0.90, 0.25, 0.10),
        help="Vùng crop tương đối x,y,width,height (mặc định 0,0.90,0.25,0.10)",
    )
    parser.add_argument(
        "--failed-crops",
        help="Thư mục tùy chọn để lưu vùng crop của các ảnh OCR thất bại",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        pytesseract.get_tesseract_version()
    except (OSError, pytesseract.TesseractNotFoundError) as exc:
        print(
            "ERROR: Không tìm thấy Tesseract. Hãy cài Tesseract và bảo đảm lệnh "
            f"tesseract có trong PATH. Chi tiết: {exc}",
            file=sys.stderr,
        )
        return 1
    subjects = DataScannerService(Path(args.data_dir)).scan()
    if args.subject:
        subjects = [subject for subject in subjects if subject.name == args.subject]
        if not subjects:
            print(f"ERROR: Không tìm thấy môn học {args.subject}", file=sys.stderr)
            return 1
    if not subjects:
        print("ERROR: Không tìm thấy môn học nào.", file=sys.stderr)
        return 1
    valid = failed = 0
    for subject in subjects:
        subject_valid, subject_failed = process_subject(subject, args)
        valid += subject_valid
        failed += subject_failed
    print(f"Tổng kết: {valid} đáp án hợp lệ, {failed} đáp án cần kiểm tra thủ công.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
