"""Regression checks for the normal-looking, isolated ``-t`` mode."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt5.QtWidgets import QApplication

from app.config import APP_NAME, DEFAULT_DATA_DIR, DEFAULT_DB_PATH
from app.repositories.database import Database
from app.test_mode import AIL_EXAM_POOL_SIZE, AIL_TRIAL_SUBJECT, is_trial_subject
from app.test_mode import TestMainWindow as TrialMainWindow
from app.test_mode import TestWorkspace as TrialWorkspace
from app.ui.screens import SettingsScreen

TOTAL_QUESTIONS = 500


@pytest.fixture
def trial_bank(tmp_path: Path) -> Path:
    source = tmp_path / "source" / AIL_TRIAL_SUBJECT
    images = source / "Selections_1_choose"
    images.mkdir(parents=True)
    first = images / "Q001.png"
    Image.new("RGB", (8, 8), "white").save(first)
    names = []
    for index in range(1, TOTAL_QUESTIONS + 1):
        name = f"Q{index:03d}.png"
        if index != 1:
            shutil.copyfile(first, images / name)
        names.append(f"Selections_1_choose/{name}")
    (source / "answers.csv").write_text(
        "image_name,correct_answer\n"
        + "".join(f"{name},A\n" for name in names),
        encoding="utf-8",
    )
    (source / "exam_first_154.json").write_text(
        json.dumps(
            {"subject": AIL_TRIAL_SUBJECT, "exam_image_names": names[:AIL_EXAM_POOL_SIZE]}
        ),
        encoding="utf-8",
    )
    return source


@pytest.fixture
def second_trial_bank(tmp_path: Path) -> Path:
    source = tmp_path / "source" / "CPV301_t"
    image = source / "Selections_1_choose" / "Q001.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), "white").save(image)
    (source / "answers.csv").write_text(
        "image_name,correct_answer\nSelections_1_choose/Q001.png,B\n",
        encoding="utf-8",
    )
    return source


def test_trial_import_copies_multiple_banks_and_keeps_normal_app_separate(
    tmp_path: Path, trial_bank: Path, second_trial_bank: Path
) -> None:
    workspace = TrialWorkspace(tmp_path / ".src-learning-test")
    normal_data = tmp_path / "DATA"
    normal_data.mkdir()
    normal_marker = normal_data / "unchanged.txt"
    normal_marker.write_text("normal", encoding="utf-8")
    normal_database = tmp_path / "study_progress.sqlite3"
    normal_database.write_bytes(b"normal database sentinel")

    assert workspace.install_from(trial_bank) == TOTAL_QUESTIONS
    assert workspace.install_from(second_trial_bank) == 1

    assert (workspace.data_dir / AIL_TRIAL_SUBJECT).is_dir()
    assert (workspace.data_dir / "CPV301_t").is_dir()
    assert workspace.data_dir != DEFAULT_DATA_DIR
    assert workspace.database_path != DEFAULT_DB_PATH
    assert not workspace.database_path.exists()
    assert normal_marker.read_text(encoding="utf-8") == "normal"
    assert normal_database.read_bytes() == b"normal database sentinel"
    with pytest.raises(ValueError, match="không tự ghi đè"):
        workspace.install_from(trial_bank)


def test_trial_rejects_bad_manifest_and_symlinks(
    tmp_path: Path, trial_bank: Path
) -> None:
    workspace = TrialWorkspace(tmp_path / "trial")
    manifest = trial_bank / "exam_first_154.json"
    manifest.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="Manifest"):
        workspace.install_from(trial_bank)
    assert not (workspace.data_dir / AIL_TRIAL_SUBJECT).exists()

    manifest.write_text(
        json.dumps(
            {"subject": AIL_TRIAL_SUBJECT, "exam_image_names": []}
        ),
        encoding="utf-8",
    )
    link = trial_bank / "outside"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Nền tảng không cho tạo symlink")
    with pytest.raises(ValueError, match="symlink"):
        workspace.install_from(trial_bank)


def test_test_window_looks_normal_and_shows_all_trial_subjects(
    tmp_path: Path, trial_bank: Path, second_trial_bank: Path
) -> None:
    application = QApplication.instance() or QApplication([])
    workspace = TrialWorkspace(tmp_path / "trial")
    workspace.install_from(trial_bank)
    workspace.install_from(second_trial_bank)
    shutil.copytree(second_trial_bank, workspace.data_dir / "NORMAL101")
    database = Database(workspace.database_path)
    window = TrialMainWindow(database, workspace)
    window.show()
    try:
        deadline = time.monotonic() + 5
        while window._scan_running and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        application.processEvents()
        assert window.windowTitle() == APP_NAME
        assert set(window.subjects) == {AIL_TRIAL_SUBJECT, "CPV301_t"}
        assert set(window.home._card_widgets) == {AIL_TRIAL_SUBJECT, "CPV301_t"}
        assert window.subjects[AIL_TRIAL_SUBJECT].question_count == TOTAL_QUESTIONS
        assert window.data_dir == workspace.data_dir
        assert window.app_header.data_import_button.isVisibleTo(window)
        window.current_subject = window.subjects[AIL_TRIAL_SUBJECT]
        assert len(window._exam_service().eligible_questions(["Selections_1_choose"])) == 154
        window.current_subject = window.subjects["CPV301_t"]
        assert len(window._exam_service().eligible_questions(["Selections_1_choose"])) == 1
        assert database.get_setting("data_dir") == str(workspace.data_dir)
        window.show_settings()
        assert isinstance(window._dynamic_page, SettingsScreen)
        assert window._dynamic_page.data_path.isReadOnly()
        assert window._dynamic_page.subject_management_panel.add_button.isEnabled()
    finally:
        window.close()
        database.close()


def test_trial_name_filter() -> None:
    assert is_trial_subject("AIL303M_t")
    assert is_trial_subject("CPV301_t")
    assert not is_trial_subject("AIL303M")
    assert not is_trial_subject(".hidden_t")
