from __future__ import annotations

from datetime import datetime, timezone

from PIL import Image

from tools.analyze_mock_exam_frequency import (
    DEFAULT_DATABASE_PATH,
    PROJECT_ROOT,
    make_figure,
    open_database,
    reserve_output_paths,
)


def test_default_database_is_anchored_to_project_root() -> None:
    assert DEFAULT_DATABASE_PATH == PROJECT_ROOT / "study_progress.sqlite3"


def test_open_database_does_not_create_a_missing_file(tmp_path) -> None:
    missing_database = tmp_path / "study_progress.sqlite3"

    try:
        open_database(missing_database)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Expected a missing database to be rejected")

    assert not missing_database.exists()


def test_output_paths_use_subject_date_and_unique_timestamp(tmp_path) -> None:
    generated_at = datetime(2026, 8, 10, 9, 5, 7, tzinfo=timezone.utc)

    first_png, first_csv = reserve_output_paths(tmp_path, "ITE303c", generated_at)

    assert first_png.parent == tmp_path / "ITE303c" / "Date-of-Statistical_10-08-26"
    assert first_png.name == (
        "mock_exam_question_frequency_ITE303c_2026-08-10_09-05-07.png"
    )
    assert first_csv.name == (
        "mock_exam_question_frequency_ITE303c_2026-08-10_09-05-07.csv"
    )

    first_png.parent.mkdir(parents=True)
    first_png.touch()
    second_png, second_csv = reserve_output_paths(tmp_path, "ITE303c", generated_at)

    assert second_png.stem.endswith("_02")
    assert second_csv.stem.endswith("_02")


def test_figure_renderer_writes_expected_canvas(tmp_path) -> None:
    rows = [
        {
            "question_id": f"q-{index}",
            "subject": "TEST101",
            "category": category,
            "relative_path": f"{category}/q-{index}.png",
            "appearances": appearances,
            "total_attempts": appearances,
            "wrong_count": 0,
            "error_rate": 0.0,
        }
        for index, (category, appearances) in enumerate(
            [
                ("Selections_1_choose", 7),
                ("Selections_Multiple_choose", 4),
                ("True_False", 2),
                ("Fill_blanks", 0),
            ]
        )
    ]
    destination = tmp_path / "figure.png"

    make_figure(rows, exam_count=3, subject="TEST101", destination=destination)

    with Image.open(destination) as image:
        assert image.size == (1800, 1450)
