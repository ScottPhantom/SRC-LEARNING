"""Regression checks for the normal-looking, isolated ``-t`` mode."""

from __future__ import annotations

import json
import os
import shutil
import stat
import time
from pathlib import Path
from zipfile import ZipFile, ZipInfo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt5.QtWidgets import QApplication

from app.config import APP_NAME, DEFAULT_DATA_DIR, DEFAULT_DB_PATH
from app.controllers.main_controller import MainWindow
from app.repositories.database import Database
from app.services.data_package_installer import DataPackageError
from app.test_mode import (
    AIL_EXAM_POOL_SIZE,
    AIL_TRIAL_SUBJECT,
    SSG_TRIAL_SUBJECT,
    is_trial_subject,
)
from app.test_mode import TestMainWindow as TrialMainWindow
from app.test_mode import TestWorkspace as TrialWorkspace
from app.ui.screens import SettingsScreen

TOTAL_QUESTIONS = 500
SSG_TRIAL_QUESTIONS = 160


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


@pytest.fixture
def ssg_trial_bank(tmp_path: Path, second_trial_bank: Path) -> Path:
    source = tmp_path / "source" / SSG_TRIAL_SUBJECT
    shutil.copytree(second_trial_bank, source)
    images = source / "Selections_1_choose"
    first = images / "Q001.png"
    names = [f"Selections_1_choose/Q{index:03d}.png" for index in range(1, SSG_TRIAL_QUESTIONS + 1)]
    for name in names[1:]:
        shutil.copyfile(first, source / name)
    (source / "answers.csv").write_text(
        "image_name,correct_answer\n" + "".join(f"{name},B\n" for name in names),
        encoding="utf-8",
    )
    return source


def test_trial_import_copies_multiple_banks_and_keeps_normal_app_separate(
    tmp_path: Path, trial_bank: Path, second_trial_bank: Path, ssg_trial_bank: Path
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
    assert workspace.install_from(ssg_trial_bank) == SSG_TRIAL_QUESTIONS

    assert (workspace.data_dir / AIL_TRIAL_SUBJECT).is_dir()
    assert (workspace.data_dir / "CPV301_t").is_dir()
    copied_ssg = workspace.data_dir / SSG_TRIAL_SUBJECT
    assert copied_ssg.is_dir()
    assert not copied_ssg.is_symlink()
    assert (copied_ssg / "answers.csv").read_bytes() == (
        ssg_trial_bank / "answers.csv"
    ).read_bytes()
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


@pytest.mark.parametrize(
    ("bank_fixture", "wrapper", "expected_count"),
    [
        ("ssg_trial_bank", "", SSG_TRIAL_QUESTIONS),
        ("second_trial_bank", "", 1),
        ("second_trial_bank", "DATA/", 1),
    ],
    ids=["legacy-ssg-archive", "trial-at-root", "trial-under-data"],
)
def test_trial_zip_imports_one_supported_subject_with_complete_keys(
    tmp_path: Path, request: pytest.FixtureRequest, bank_fixture: str,
    wrapper: str, expected_count: int,
) -> None:
    bank: Path = request.getfixturevalue(bank_fixture)
    workspace = TrialWorkspace(tmp_path / "trial")
    archive = tmp_path / "shared-questions.zip"
    with ZipFile(archive, "w") as bundle:
        for source in sorted(bank.rglob("*")):
            if source.is_file():
                relative = source.relative_to(bank).as_posix()
                bundle.write(source, f"{wrapper}{bank.name}/{relative}")
        if bank.name == SSG_TRIAL_SUBJECT:
            # The previously shared portable archive included this sibling file.
            bundle.writestr("SSG150t-code.patch", "legacy patch")

    assert workspace.install_from_zip(archive) == expected_count

    target = workspace.data_dir / bank.name
    assert (target / "answers.csv").read_bytes() == (bank / "answers.csv").read_bytes()
    assert len(list((target / "Selections_1_choose").glob("*.png"))) == expected_count
    assert list(workspace.data_dir.iterdir()) == [target]


@pytest.mark.parametrize(
    "subject_folders",
    [("SSG105t",), ("CPV301_t", "DATA/DAP391m_t")],
    ids=["normal-subject-only", "ambiguous-trial-subjects"],
)
def test_trial_zip_requires_exactly_one_supported_subject(
    tmp_path: Path, second_trial_bank: Path, subject_folders: tuple[str, ...]
) -> None:
    workspace = TrialWorkspace(tmp_path / "trial")
    archive = tmp_path / "unsupported.zip"
    question = "Selections_1_choose/Q001.png"
    with ZipFile(archive, "w") as bundle:
        for subject_folder in subject_folders:
            bundle.write(second_trial_bank / question, f"{subject_folder}/{question}")
            bundle.write(second_trial_bank / "answers.csv", f"{subject_folder}/answers.csv")

    with pytest.raises(DataPackageError, match="đúng một thư mục môn học thử"):
        workspace.install_from_zip(archive)

    assert not list(workspace.data_dir.iterdir())


@pytest.mark.parametrize(
    "unsafe_member",
    [None, "link", "answers.csv:alternate", "CON.txt"],
    ids=["missing-answers", "symlink", "windows-stream", "windows-device"],
)
def test_trial_zip_rejects_incomplete_keys_or_unsafe_member(
    tmp_path: Path, second_trial_bank: Path, unsafe_member: str | None
) -> None:
    workspace = TrialWorkspace(tmp_path / "trial")
    archive = tmp_path / "invalid.zip"
    question = "Selections_1_choose/Q001.png"
    with ZipFile(archive, "w") as bundle:
        bundle.write(second_trial_bank / question, f"{SSG_TRIAL_SUBJECT}/{question}")
        if unsafe_member is None:
            bundle.writestr(f"{SSG_TRIAL_SUBJECT}/answers.csv", "image_name,correct_answer\n")
        else:
            bundle.write(second_trial_bank / "answers.csv", f"{SSG_TRIAL_SUBJECT}/answers.csv")
            entry = ZipInfo(f"{SSG_TRIAL_SUBJECT}/{unsafe_member}")
            if unsafe_member == "link":
                entry.create_system = 3
                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(entry, "answers.csv")

    with pytest.raises(DataPackageError, match="không an toàn" if unsafe_member else "answers.csv"):
        workspace.install_from_zip(archive)

    assert not (workspace.data_dir / SSG_TRIAL_SUBJECT).exists()


def test_normal_window_hides_trial_subjects_even_with_trial_data_path(
    tmp_path: Path, second_trial_bank: Path
) -> None:
    application = QApplication.instance() or QApplication([])
    workspace = TrialWorkspace(tmp_path / ".src-learning-test")
    workspace.prepare()
    shutil.copytree(second_trial_bank, workspace.data_dir / second_trial_bank.name)
    shutil.copytree(second_trial_bank, workspace.data_dir / SSG_TRIAL_SUBJECT)
    shutil.copytree(second_trial_bank, workspace.data_dir / "SSG105t")
    database = Database(tmp_path / "study_progress.sqlite3")
    database.set_setting("data_dir", str(workspace.data_dir))
    window = MainWindow(database)
    window.show()
    try:
        deadline = time.monotonic() + 5
        while window._scan_running and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        application.processEvents()
        assert set(window.subjects) == {"SSG105t"}
        assert set(window.home._card_widgets) == {"SSG105t"}
    finally:
        window.close()
        database.close()


def test_test_window_looks_normal_and_shows_all_trial_subjects(
    tmp_path: Path, trial_bank: Path, second_trial_bank: Path, ssg_trial_bank: Path
) -> None:
    application = QApplication.instance() or QApplication([])
    workspace = TrialWorkspace(tmp_path / "trial")
    workspace.install_from(trial_bank)
    workspace.install_from(second_trial_bank)
    workspace.install_from(ssg_trial_bank)
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
        expected_subjects = {AIL_TRIAL_SUBJECT, "CPV301_t", SSG_TRIAL_SUBJECT}
        assert set(window.subjects) == expected_subjects
        assert set(window.home._card_widgets) == expected_subjects
        assert window.subjects[AIL_TRIAL_SUBJECT].question_count == TOTAL_QUESTIONS
        assert window.data_dir == workspace.data_dir
        assert window.app_header.data_import_button.isVisibleTo(window)
        window.current_subject = window.subjects[AIL_TRIAL_SUBJECT]
        assert len(window._exam_service().eligible_questions(["Selections_1_choose"])) == 154
        window.current_subject = window.subjects["CPV301_t"]
        assert len(window._exam_service().eligible_questions(["Selections_1_choose"])) == 1
        window.current_subject = window.subjects[SSG_TRIAL_SUBJECT]
        assert len(window._exam_service().eligible_questions(["Selections_1_choose"])) == SSG_TRIAL_QUESTIONS
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
    assert is_trial_subject("SSG150t")
    assert is_trial_subject("ssg150T")
    assert not is_trial_subject("SSG105t")
    assert not is_trial_subject("OTHERt")
    assert not is_trial_subject(".SSG150t")
    assert not is_trial_subject("AIL303M")
    assert not is_trial_subject(".hidden_t")
