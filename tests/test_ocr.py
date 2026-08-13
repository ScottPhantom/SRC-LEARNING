from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pytest

from app.domain.models import Question
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
    monkeypatch.setattr(
        build_answers.pytesseract, "image_to_string", lambda *a, **k: ocr_text
    )
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


def test_versioned_bank_writes_ocr_result_to_pending_file(tmp_path) -> None:
    subject_path = tmp_path / "TEST101"
    subject_path.mkdir()
    assert build_answers.answer_output_path(subject_path).name == "answers.csv"

    versions = subject_path / "answer_versions"
    versions.mkdir()
    (versions / "manifest.json").write_text("{}", encoding="utf-8")

    assert build_answers.answer_output_path(subject_path).name == "answers.pending.csv"


def test_identical_versioned_result_does_not_create_pending_file(tmp_path) -> None:
    subject_path = tmp_path / "TEST101"
    versions = subject_path / "answer_versions"
    versions.mkdir(parents=True)
    (versions / "manifest.json").write_text("{}", encoding="utf-8")
    pending = subject_path / "answers.pending.csv"
    pending.write_text("stale pending", encoding="utf-8")
    active = {
        "Selections_1_choose/Câu 1.png": "A",
        "True_False/Câu 2.png": "B",
    }
    rows = [
        ("Selections_1_choose/Câu 1.png", "a"),
        ("True_False\\Câu 2.png", "B"),
    ]

    output_path, status = build_answers.publish_answers(subject_path, active, rows)

    assert output_path == pending
    assert status == "unchanged"
    assert not pending.exists()


def test_changed_versioned_result_writes_pending_file(tmp_path) -> None:
    subject_path = tmp_path / "TEST101"
    versions = subject_path / "answer_versions"
    versions.mkdir(parents=True)
    (versions / "manifest.json").write_text("{}", encoding="utf-8")
    active = {"Selections_1_choose/Câu 1.png": "A"}
    rows = [("Selections_1_choose/Câu 1.png", "B")]

    output_path, status = build_answers.publish_answers(subject_path, active, rows)

    assert status == "written"
    assert build_answers.read_existing(output_path) == {
        "Selections_1_choose/Câu 1.png": "B"
    }


def test_manual_answer_repeats_until_valid_for_multiple_choice() -> None:
    question = Question(
        id="q-186",
        subject="ITE303c",
        category="Selections_Multiple_choose",
        relative_path="Selections_Multiple_choose/Câu 186.png",
        absolute_path=Path("/DATA/ITE303c/Selections_Multiple_choose/Câu 186.png"),
    )
    answers = iter(["A", "A D"])
    messages: list[str] = []

    result = build_answers.prompt_for_manual_answer(
        question,
        input_func=lambda _prompt: next(answers),
        output_func=messages.append,
    )

    assert result == "AD"
    assert any("không hợp lệ" in message for message in messages)
    assert any("Đã nhận đáp án thủ công: AD" in message for message in messages)


def test_manual_answer_can_be_explicitly_skipped() -> None:
    question = Question(
        id="q-298",
        subject="ITE303c",
        category="True_False",
        relative_path="True_False/Câu 298.png",
        absolute_path=Path("/DATA/ITE303c/True_False/Câu 298.png"),
    )

    assert (
        build_answers.prompt_for_manual_answer(
            question,
            input_func=lambda _prompt: "skip",
            output_func=lambda _message: None,
        )
        == ""
    )
