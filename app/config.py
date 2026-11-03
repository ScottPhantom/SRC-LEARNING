from __future__ import annotations

import os
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
DEFAULT_DATA_DIR = (
    STATE_DIR / "DATA" if getattr(sys, "frozen", False) else APP_DIR / "DATA"
)
DEFAULT_DB_PATH = STATE_DIR / "study_progress.sqlite3"

# Published CSV of the GOOGLE_IDS tab only; never the private Sheet edit URL.
# A catalog_source_url.txt file beside the executable can override this URL
# without rebuilding when the publisher rotates the public link.
CATALOG_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRvie1ajc8YExu-3KEVIxLa8fEXWdHlxim_1t1Z56uZhi8Pydvs_KwgcVbCwhQhwnJWEuhmosBX3r2h/"
    "pub?gid=105&single=true&output=csv"
)


def catalog_csv_url() -> str:
    """Resolve the public catalog URL without requiring a new executable build.

    A maintainer may ship catalog_source_url.txt beside the executable. The
    environment variable is useful for development and automated tests.
    """
    override = os.environ.get("SRC_LEARNING_CATALOG_CSV_URL", "").strip()
    if override:
        return override
    source_file = APP_DIR / "catalog_source_url.txt"
    try:
        if (
            source_file.is_file()
            and not source_file.is_symlink()
            and source_file.stat().st_size <= 4096
        ):
            configured = source_file.read_text(encoding="utf-8-sig").strip()
            if configured:
                return configured
    except (OSError, UnicodeError):
        pass
    return CATALOG_CSV_URL

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
