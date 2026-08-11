from __future__ import annotations

import argparse
import csv
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "study_progress.sqlite3"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "docs"

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
ALERT = "#B42318"
FALLBACK_COLORS = ("#0EA5E9", "#D946EF", "#84CC16", "#EAB308", "#EC4899")
CATEGORY_LABELS = {
    "Selections_1_choose": "Chọn một đáp án",
    "Selections_Multiple_choose": "Chọn nhiều đáp án",
    "True_False": "Đúng / Sai",
    "Fill_blanks": "Điền khuyết",
}


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


def text_width(
    draw: ImageDraw.ImageDraw, text: str, size: int, bold: bool = False
) -> int:
    box = draw.textbbox((0, 0), text, font=font(size, bold))
    return int(box[2] - box[0])


def fitted_font_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    preferred: int,
    maximum_width: int,
    *,
    bold: bool = False,
    minimum: int = 18,
) -> int:
    size = preferred
    while size > minimum and text_width(draw, text, size, bold) > maximum_width:
        size -= 1
    return size


def category_color(category: str) -> str:
    if category in CATEGORY_COLORS:
        return CATEGORY_COLORS[category]
    index = sum(ord(char) for char in category) % len(FALLBACK_COLORS)
    return FALLBACK_COLORS[index]


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category.replace("_", " "))


def draw_legend(
    draw: ImageDraw.ImageDraw,
    categories: list[str],
    *,
    left: int,
    top: int,
    right: int,
) -> int:
    x = left
    y = top
    row_height = 34
    for category in categories:
        label = category_label(category)
        item_width = 28 + text_width(draw, label, 18) + 40
        if x + item_width > right and x > left:
            x = left
            y += row_height
        draw.rounded_rectangle(
            (x, y + 4, x + 20, y + 24), radius=5, fill=category_color(category)
        )
        draw_text(draw, (x + 30, y + 14), label, 18, fill=MUTED, anchor="lm")
        x += item_width
    return y + row_height


def draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    left: int,
    top: int,
    maximum_width: int,
    size: int,
    fill: str = MUTED,
    line_height: int | None = None,
) -> int:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and text_width(draw, candidate, size) > maximum_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    step = line_height or int(size * 1.35)
    for index, line in enumerate(lines):
        draw_text(draw, (left, top + index * step), line, size, fill=fill)
    return top + len(lines) * step


def make_figure(
    rows: list[dict[str, object]],
    exam_count: int,
    subject: str,
    destination: Path,
) -> None:
    width, height = 1800, 1450
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    appearances = [int(row["appearances"]) for row in rows]
    average = sum(appearances) / len(appearances)
    unseen = sum(value == 0 for value in appearances)
    categories = sorted({str(row["category"]) for row in rows})

    title = f"Phân phối tần suất câu hỏi Mock Exam — {subject}"
    title_size = fitted_font_size(draw, title, 46, width - 180, bold=True, minimum=30)
    draw_text(
        draw,
        (90, 65),
        title,
        title_size,
        bold=True,
    )
    summary = (
        f"{len(rows)} câu  •  {exam_count} bài đã nộp  •  {sum(appearances):,} lượt chọn  •  "
        f"Thấp nhất {min(appearances)}  •  Trung bình {average:.2f}  •  Cao nhất {max(appearances)}"
    )
    summary_size = fitted_font_size(draw, summary, 24, width - 180, minimum=18)
    draw_text(
        draw,
        (90, 125),
        summary,
        summary_size,
        fill=MUTED,
    )

    # Ranked per-question exposure chart.
    panel_left, panel_top, panel_right, panel_bottom = 70, 185, 1730, 795
    draw.rounded_rectangle(
        (panel_left, panel_top, panel_right, panel_bottom), radius=22, fill=PANEL
    )
    draw_text(draw, (105, 215), "Mức độ phủ của từng câu hỏi", 29, bold=True)
    draw_text(
        draw,
        (105, 258),
        "Mỗi cột là một câu; câu xuất hiện nhiều được xếp về bên trái.",
        20,
        fill=MUTED,
    )
    left, top, right, bottom = 110, 315, 1690, 685
    max_value = max(appearances) or 1
    tick_step = max(1, math.ceil(max_value / 5))
    ticks = list(range(0, max_value + 1, tick_step))
    for tick in ticks:
        y = bottom - (tick / max_value) * (bottom - top)
        draw.line((left, y, right, y), fill=GRID, width=2)
        draw_text(draw, (left - 18, y), str(tick), 20, fill=MUTED, anchor="rm")
    bar_width = (right - left) / len(rows)
    for index, row in enumerate(rows):
        value = int(row["appearances"])
        x0 = left + index * bar_width
        x1 = max(x0 + 1, left + (index + 1) * bar_width - 1)
        y = bottom - (value / max_value) * (bottom - top)
        color = category_color(str(row["category"]))
        draw.rectangle((x0, y, x1, bottom), fill=color)
    mean_y = bottom - (average / max_value) * (bottom - top)
    draw.line((left, mean_y, right, mean_y), fill=ALERT, width=3)
    mean_label = f"Trung bình {average:.2f}"
    mean_label_width = text_width(draw, mean_label, 19, True)
    draw.rounded_rectangle(
        (right - mean_label_width - 24, mean_y - 36, right, mean_y - 7),
        radius=7,
        fill="white",
        outline=ALERT,
        width=2,
    )
    draw_text(
        draw,
        (right - 11, mean_y - 21),
        mean_label,
        19,
        fill=ALERT,
        bold=True,
        anchor="rm",
    )
    draw.line((left, bottom, right, bottom), fill=INK, width=2)
    draw_legend(draw, categories, left=110, top=724, right=1690)

    # Distribution histogram.
    lower_top, lower_bottom = 835, 1315
    draw.rounded_rectangle((70, lower_top, 925, lower_bottom), radius=22, fill=PANEL)
    draw_text(draw, (105, 872), "Số câu theo mức tần suất", 27, bold=True)
    draw_text(
        draw,
        (105, 912),
        "Chiều cao cột là số lượng câu hỏi ở mỗi mức xuất hiện.",
        18,
        fill=MUTED,
    )
    histogram = Counter(appearances)
    h_left, h_top, h_right, h_bottom = 115, 970, 880, 1195
    max_bucket = max(histogram.values())
    bucket_width = (h_right - h_left) / (max_value + 1)
    for value in range(max_value + 1):
        count = histogram[value]
        x0 = h_left + value * bucket_width + 2
        x1 = h_left + (value + 1) * bucket_width - 2
        y = h_bottom - (count / max_bucket) * (h_bottom - h_top)
        draw.rounded_rectangle((x0, y, x1, h_bottom), radius=3, fill="#246BFD")
        if count and (count == max_bucket or value in {0, max_value}):
            draw_text(
                draw, ((x0 + x1) / 2, y - 9), str(count), 17, bold=True, anchor="mb"
            )
    draw.line((h_left, h_bottom, h_right, h_bottom), fill=INK, width=2)
    for value in range(0, max_value + 1, max(1, math.ceil(max_value / 8))):
        x = h_left + (value + 0.5) * bucket_width
        draw_text(draw, (x, h_bottom + 25), str(value), 17, fill=MUTED, anchor="mm")
    draw_text(
        draw,
        ((h_left + h_right) / 2, 1264),
        f"{unseen} câu chưa xuất hiện  •  Gini {gini(appearances):.3f}",
        18,
        fill=MUTED,
        anchor="mm",
    )

    # Category averages expose the configuration-selection caveat.
    draw.rounded_rectangle((965, lower_top, 1730, lower_bottom), radius=22, fill=PANEL)
    draw_text(draw, (1000, 872), "Tần suất trung bình theo loại", 27, bold=True)
    draw_text(
        draw,
        (1000, 912),
        "So sánh trực tiếp giữa các nhóm câu hỏi trong ngân hàng.",
        18,
        fill=MUTED,
    )
    category_values: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        category_values[str(row["category"])].append(int(row["appearances"]))
    category_averages = [
        (category, sum(values) / len(values), len(values))
        for category, values in category_values.items()
    ]
    category_averages.sort(key=lambda item: item[1], reverse=True)
    c_left, c_right = 1255, 1585
    c_max = max(value for _, value, _ in category_averages) or 1
    available_height = 310
    row_height = min(68, max(44, available_height // max(1, len(category_averages))))
    first_y = 980
    for index, (category, value, count) in enumerate(category_averages):
        y = first_y + index * row_height
        label = category_label(category)
        label_size = fitted_font_size(draw, label, 18, 225, minimum=14)
        draw_text(draw, (1225, y), label, label_size, fill=MUTED, anchor="rm")
        draw.rounded_rectangle(
            (c_left, y - 12, c_left + (value / c_max) * (c_right - c_left), y + 12),
            radius=8,
            fill=category_color(category),
        )
        draw_text(
            draw,
            (c_right + 18, y),
            f"{value:.2f}  •  {count} câu",
            17,
            bold=True,
            anchor="lm",
        )

    draw_wrapped_text(
        draw,
        "Nguồn: study_progress.sqlite3, chỉ tính Mock Exam đã nộp. Việc người dùng chọn category khác nhau cũng làm thay đổi exposure.",
        left=90,
        top=1365,
        maximum_width=width - 180,
        size=19,
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
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--subject")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def open_database(database_path: Path) -> sqlite3.Connection:
    """Open the existing progress database without ever creating a new file."""
    resolved_path = database_path.expanduser().resolve()
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy database: {resolved_path}")
    return sqlite3.connect(f"{resolved_path.as_uri()}?mode=ro", uri=True)


def safe_path_component(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
    return safe.strip("._") or "unknown-subject"


def reserve_output_paths(
    output_dir: Path,
    subject: str,
    generated_at: datetime,
) -> tuple[Path, Path]:
    safe_subject = safe_path_component(subject)
    date_directory = (
        output_dir
        / safe_subject
        / generated_at.strftime("Date-of-Statistical_%d-%m-%y")
    )
    timestamp = generated_at.strftime("%Y-%m-%d_%H-%M-%S")
    base_stem = f"mock_exam_question_frequency_{safe_subject}_{timestamp}"
    suffix = ""
    counter = 1
    while True:
        png_path = date_directory / f"{base_stem}{suffix}.png"
        csv_path = date_directory / f"{base_stem}{suffix}.csv"
        if not png_path.exists() and not csv_path.exists():
            return png_path, csv_path
        counter += 1
        suffix = f"_{counter:02d}"


def main() -> None:
    args = parse_args()
    with open_database(args.database) as connection:
        generated_at = datetime.now().astimezone()
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
            png_path, csv_path = reserve_output_paths(
                args.output_dir, subject, generated_at
            )
            make_figure(rows, exam_count, subject, png_path)
            write_csv(rows, csv_path)
            print(f"{subject}: {png_path} | {csv_path}")


if __name__ == "__main__":
    main()
