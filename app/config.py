from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "SRC LEARNING"
APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
STATE_DIR = (
    Path.home() / ".luyen_thi_hinh_anh"
    if getattr(sys, "frozen", False)
    else APP_DIR
)
DEFAULT_DATA_DIR = APP_DIR / "DATA"
DEFAULT_DB_PATH = STATE_DIR / "study_progress.sqlite3"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
CATEGORIES = (
    "Fill_blanks",
    "Selections_1_choose",
    "Selections_Multiple_choose",
    "True_False",
)
CATEGORY_LABELS = {
    "Fill_blanks": "Điền vào chỗ trống",
    "Selections_1_choose": "Chọn một đáp án",
    "Selections_Multiple_choose": "Chọn nhiều đáp án",
    "True_False": "Đúng / Sai",
}
MULTIPLE_CATEGORY = "Selections_Multiple_choose"
TRUE_FALSE_CATEGORY = "True_False"

# x, y, width, height -- all relative to the original image.
DEFAULT_MASK_REGION = (0.0, 0.90, 0.25, 0.10)
