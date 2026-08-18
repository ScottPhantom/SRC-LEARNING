from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytesseract

from app.domain.models import normalize_answer


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
    x2, y2 = (
        max(x1 + 1, int(width * (x + crop_width))),
        max(y1 + 1, int(height * (y + crop_height))),
    )
    return image[y1:y2, x1:x2]


def preprocess(crop: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]


def recognize(crop: np.ndarray, multiple: bool) -> str:
    """Nhận diện đáp án bằng nhiều biến thể, kể cả ký tự viết thường."""

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
