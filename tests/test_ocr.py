from __future__ import annotations

import argparse

import numpy as np
import pytest

from tools import build_answers


def test_crop_answer_uses_relative_coordinates() -> None:
    image = np.zeros((500, 1000, 3), dtype=np.uint8)
    crop = build_answers.crop_answer(image, (0.0, 0.9, 0.25, 0.1))
    assert crop.shape == (50, 250, 3)


@pytest.mark.parametrize(
    ("ocr_text", "multiple", "expected"),
    [
        (" B\n", False, "B"),
        ("d\n", False, "D"),
        ("D C B", True, "BCD"),
        ("ACD...", True, "ACD"),
    ],
)
def test_recognize_normalizes_tesseract_output(
    monkeypatch, ocr_text: str, multiple: bool, expected: str
) -> None:
    monkeypatch.setattr(build_answers.pytesseract, "image_to_string", lambda *a, **k: ocr_text)
    crop = np.full((50, 250, 3), 255, dtype=np.uint8)
    assert build_answers.recognize(crop, multiple) == expected


def test_recognize_retries_when_first_ocr_result_is_empty(monkeypatch) -> None:
    results = iter(["", "b\n"])
    configs: list[str] = []

    def fake_ocr(*_args, **kwargs) -> str:
        configs.append(kwargs["config"])
        return next(results)

    monkeypatch.setattr(build_answers.pytesseract, "image_to_string", fake_ocr)
    crop = np.full((50, 250, 3), 255, dtype=np.uint8)

    assert build_answers.recognize(crop, multiple=False) == "B"
    assert all("ABCDEFGHabcdefgh" in config for config in configs)


def test_parse_region_rejects_outside_image() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        build_answers.parse_region("0.9,0.9,0.2,0.2")
