from __future__ import annotations

import argparse
import csv
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CATEGORY_COLORS = {
    "Selections_1_choose": "#246BFD",
    "Selections_Multiple_choose": "#8B5CF6",
    "True_False": "#F97316",
    "Fill_blanks": "#16A085",
}
INK = "#172033"
MUTED = "#667085"
GRID = "#D9E1EC"
PANEL = "#F7F9FC"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
        if bold
        else Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        if bold
        else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def load_rows(connection: sqlite3.Connection, subject: str) -> list[dict[str, object]]:
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """SELECT q.id, q.subject, q.category, q.relative_path,
        COUNT(ea.question_id) appearances,
        COALESCE(qes.total_attempts, 0) total_attempts,
        COALESCE(qes.wrong_count, 0) wrong_count
        FROM questions q
        LEFT JOIN exam_answers ea ON ea.question_id=q.id
        LEFT JOIN question_error_stats qes ON qes.question_id=q.id
        WHERE q.active=1 AND q.subject=?
        GROUP BY q.id
        ORDER BY appearances DESC, q.category, q.relative_path""",
        (subject,),
    ).fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        attempts = int(row["total_attempts"])
        wrong = int(row["wrong_count"])
        result.append(
            {
                "question_id": str(row["id"]),
                "subject": str(row["subject"]),
                "category": str(row["category"]),
                "relative_path": str(row["relative_path"]),
                "appearances": int(row["appearances"]),
                "total_attempts": attempts,
                "wrong_count": wrong,
                "error_rate": wrong / attempts if attempts else 0.0,
            }
        )
    return result


def gini(values: list[int]) -> float:
    ordered = sorted(values)
    total = sum(ordered)
    if not ordered or total == 0:
        return 0.0
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return (2 * weighted) / (len(ordered) * total) - (len(ordered) + 1) / len(ordered)


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    size: int,
    *,
    fill: str = INK,
    bold: bool = False,
    anchor: str | None = None,
) -> None:
    draw.text(xy, text, font=font(size, bold), fill=fill, anchor=anchor)


def make_figure(
    rows: list[dict[str, object]],
    exam_count: int,
    subject: str,
    destination: Path,
) -> None:
    width, height = 1800, 1180
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    appearances = [int(row["appearances"]) for row in rows]
    average = sum(appearances) / len(appearances)
    unseen = sum(value == 0 for value in appearances)

    draw_text(
        draw,
        (90, 65),
        f"Tần suất xuất hiện câu hỏi Mock Exam — {subject}",
        45,
        bold=True,
    )
    draw_text(
        draw,
        (90, 125),
        (
            f"{len(rows)} câu • {exam_count} bài đã nộp • {sum(appearances):,} lượt chọn • "
            f"min {min(appearances)} / trung bình {average:.2f} / max {max(appearances)}"
        ),
        25,
        fill=MUTED,
    )

    # Ranked per-question exposure chart.
    left, top, right, bottom = 105, 225, 1710, 685
    draw.rounded_rectangle((70, 185, 1740, 735), radius=22, fill=PANEL)
    draw_text(draw, (105, 205), "Mỗi cột là một câu hỏi, xếp theo số lần xuất hiện", 27, bold=True)
    max_value = max(appearances) or 1
    for tick in range(0, max_value + 1, max(1, math.ceil(max_value / 5))):
        y = bottom - (tick / max_value) * (bottom - top)
        draw.line((left, y, right, y), fill=GRID, width=2)
        draw_text(draw, (left - 18, y), str(tick), 20, fill=MUTED, anchor="rm")
    bar_width = (right - left) / len(rows)
    for index, row in enumerate(rows):
        value = int(row["appearances"])
        x0 = left + index * bar_width
        x1 = max(x0 + 1, left + (index + 1) * bar_width - 1)
        y = bottom - (value / max_value) * (bottom - top)
        color = CATEGORY_COLORS.get(str(row["category"]), "#64748B")
        draw.rectangle((x0, y, x1, bottom), fill=color)
    mean_y = bottom - (average / max_value) * (bottom - top)
    draw.line((left, mean_y, right, mean_y), fill="#B42318", width=3)
    draw_text(
        draw,
        (right - 5, mean_y - 10),
        f"Trung bình {average:.2f}",
        20,
        fill="#B42318",
        bold=True,
        anchor="rb",
    )
    draw.line((left, bottom, right, bottom), fill=INK, width=2)
    draw_text(draw, ((left + right) / 2, bottom + 37), "Câu hỏi (xếp hạng)", 21, fill=MUTED, anchor="mm")

    legend_x = 110
    for category, color in CATEGORY_COLORS.items():
        draw.rounded_rectangle((legend_x, 697, legend_x + 22, 719), radius=5, fill=color)
        draw_text(draw, (legend_x + 31, 708), category, 18, fill=MUTED, anchor="lm")
        legend_x += 365

    # Distribution histogram.
    draw.rounded_rectangle((70, 765, 935, 1080), radius=22, fill=PANEL)
    draw_text(draw, (105, 790), "Phân phối số lần xuất hiện", 27, bold=True)
    histogram = Counter(appearances)
    h_left, h_top, h_right, h_bottom = 115, 855, 890, 1025
    max_bucket = max(histogram.values())
    bucket_width = (h_right - h_left) / (max_value + 1)
    for value in range(max_value + 1):
        count = histogram[value]
        x0 = h_left + value * bucket_width + 2
        x1 = h_left + (value + 1) * bucket_width - 2
        y = h_bottom - (count / max_bucket) * (h_bottom - h_top)
        draw.rounded_rectangle((x0, y, x1, h_bottom), radius=3, fill="#246BFD")
        if count and (count == max_bucket or value in {0, max_value}):
            draw_text(draw, ((x0 + x1) / 2, y - 9), str(count), 17, bold=True, anchor="mb")
    draw.line((h_left, h_bottom, h_right, h_bottom), fill=INK, width=2)
    for value in range(0, max_value + 1, max(1, math.ceil(max_value / 8))):
        x = h_left + (value + 0.5) * bucket_width
        draw_text(draw, (x, h_bottom + 23), str(value), 17, fill=MUTED, anchor="mm")
    draw_text(
        draw,
        ((h_left + h_right) / 2, 1061),
        f"Số lần xuất hiện • {unseen} câu chưa xuất hiện • Gini {gini(appearances):.3f}",
        18,
        fill=MUTED,
        anchor="mm",
    )

    # Category averages expose the configuration-selection caveat.
    draw.rounded_rectangle((965, 765, 1740, 1080), radius=22, fill=PANEL)
    draw_text(draw, (1000, 790), "Trung bình theo loại câu", 27, bold=True)
    category_values: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        category_values[str(row["category"])].append(int(row["appearances"]))
    category_averages = [
        (category, sum(values) / len(values), len(values))
        for category, values in category_values.items()
    ]
    category_averages.sort(key=lambda item: item[1], reverse=True)
    c_left, c_right = 1260, 1660
    c_max = max(value for _, value, _ in category_averages) or 1
    for index, (category, value, count) in enumerate(category_averages):
        y = 860 + index * 50
        draw_text(draw, (1235, y), category, 18, fill=MUTED, anchor="rm")
        draw.rounded_rectangle(
            (c_left, y - 12, c_left + (value / c_max) * (c_right - c_left), y + 12),
            radius=8,
            fill=CATEGORY_COLORS.get(category, "#64748B"),
        )
        draw_text(draw, (c_right + 15, y), f"{value:.2f}  (n={count})", 18, bold=True, anchor="lm")

    draw_text(
        draw,
        (90, 1140),
        "Nguồn: study_progress.sqlite3, chỉ tính Mock Exam đã nộp. Việc người dùng chọn category khác nhau cũng làm thay đổi exposure.",
        20,
        fill=MUTED,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, optimize=True)


def write_csv(rows: list[dict[str, object]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Mock Exam question exposure.")
    parser.add_argument("--database", type=Path, default=Path("study_progress.sqlite3"))
    parser.add_argument("--subject")
    parser.add_argument("--output-dir", type=Path, default=Path("docs"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    connection = sqlite3.connect(args.database)
    subjects = [
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT subject FROM questions WHERE active=1 ORDER BY subject"
        )
    ]
    if args.subject:
        subjects = [args.subject]
    for subject in subjects:
        rows = load_rows(connection, subject)
        if not rows:
            continue
        exam_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM exam_attempts WHERE subject=?", (subject,)
            ).fetchone()[0]
        )
        safe_subject = "".join(char if char.isalnum() or char in "-_" else "_" for char in subject)
        png_path = args.output_dir / f"mock_exam_question_frequency_{safe_subject}.png"
        csv_path = args.output_dir / f"mock_exam_question_frequency_{safe_subject}.csv"
        make_figure(rows, exam_count, subject, png_path)
        write_csv(rows, csv_path)
        print(f"{subject}: {png_path} | {csv_path}")
    connection.close()


if __name__ == "__main__":
    main()
