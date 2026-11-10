"""Isolated data and progress for subjects whose folder name ends in ``_t``."""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from PyQt5.QtWidgets import QFileDialog, QMessageBox

from app.config import STATE_DIR
from app.controllers.main_controller import MainWindow
from app.domain.models import AppSettings, Subject
from app.repositories.answer_key import AnswerKeyRepository
from app.repositories.database import Database
from app.services.data_scanner import DataScannerService
from app.services.exam import ExamService
from app.services.subject_management import (
    SubjectManagementError,
    inspect_tree,
    subject_destination,
)
from app.ui.screens import SettingsScreen

LOGGER = logging.getLogger(__name__)
AIL_TRIAL_SUBJECT = "AIL303M_t"
AIL_EXAM_POOL_SIZE = 154


def is_trial_subject(name: str) -> bool:
    return bool(name) and not name.startswith(".") and name.casefold().endswith("_t")


@dataclass(frozen=True, slots=True)
class TestWorkspace:
    root: Path

    @classmethod
    def default(cls) -> TestWorkspace:
        return cls(STATE_DIR / ".src-learning-test")

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def database_path(self) -> Path:
        return self.root / "test_progress.sqlite3"

    def prepare(self) -> None:
        """Create only the private DATA root, refusing symlink redirection."""
        for path in (self.root, self.data_dir):
            if path.is_symlink():
                raise ValueError(f"Đường dẫn dữ liệu không an toàn: {path}")
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def exam_paths(subject: Subject) -> frozenset[str] | None:
        """Keep the AIL303M_t exam restricted to its original 154 images."""
        if subject.name.casefold() != AIL_TRIAL_SUBJECT.casefold():
            return None
        manifest = subject.path / "exam_first_154.json"
        if manifest.is_symlink() or not manifest.is_file():
            raise ValueError("AIL303M_t thiếu exam_first_154.json.")
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError("Không đọc được exam_first_154.json.") from exc
        if not isinstance(payload, dict):
            raise TypeError("Manifest đề thi của AIL303M_t không hợp lệ.")
        subject_name = payload.get("subject")
        if not isinstance(subject_name, str):
            raise TypeError("Manifest đề thi thiếu tên môn hợp lệ.")
        paths = payload.get("exam_image_names")
        if (
            subject_name.casefold() != AIL_TRIAL_SUBJECT.casefold()
            or not isinstance(paths, list)
            or len(paths) != AIL_EXAM_POOL_SIZE
            or any(not isinstance(path, str) for path in paths)
            or len(set(paths)) != AIL_EXAM_POOL_SIZE
        ):
            raise ValueError("Manifest AIL303M_t phải có đúng 154 đường dẫn ảnh.")
        known = {question.relative_path for question in subject.questions}
        if not set(paths) <= known:
            raise ValueError("Manifest AIL303M_t trỏ tới ảnh không còn trong thư mục môn.")
        return frozenset(paths)

    def install_from(self, source: Path) -> int:
        """Copy one local ``*_t`` folder into DATA without touching the source."""
        self.prepare()
        source = Path(source).expanduser()
        if not source.is_dir() or source.is_symlink() or not is_trial_subject(source.name):
            raise ValueError("Hãy chọn một thư mục môn có tên kết thúc bằng _t, không phải symlink.")
        target = subject_destination(self.data_dir, source.name)
        if target.exists() or target.is_symlink():
            raise ValueError(f"{source.name} đã có trong DATA thử; không tự ghi đè.")
        with TemporaryDirectory(prefix=".import-", dir=self.data_dir) as temporary:
            staging = Path(temporary)
            copied = staging / source.name
            shutil.copytree(source, copied, symlinks=True)
            if inspect_tree(copied)[2]:
                raise ValueError("Gói môn chứa symlink; không thể nhập an toàn.")
            subjects = DataScannerService(staging).scan()
            if len(subjects) != 1 or subjects[0].name != source.name:
                raise ValueError("Không quét được gói môn đã chọn.")
            subject = subjects[0]
            if not subject.questions or subject.invalid_images:
                raise ValueError("Gói môn thiếu hoặc có ảnh câu hỏi không hợp lệ.")
            report = AnswerKeyRepository().load(subject.path, subject.questions)
            if report.invalid or report.duplicates or report.unknown_paths:
                raise ValueError("answers.csv của gói môn có dòng không hợp lệ.")
            self.exam_paths(subject)
            if target.exists() or target.is_symlink():
                raise ValueError(f"{source.name} đã xuất hiện trong lúc nhập; không ghi đè.")
            os.replace(copied, target)
        return subject.question_count


class TestMainWindow(MainWindow):
    """Normal-looking app window bound exclusively to the private workspace."""

    def __init__(self, database: Database, workspace: TestWorkspace):
        self.test_workspace = workspace
        database.set_setting("data_dir", str(workspace.data_dir))
        super().__init__(database)

    def _apply_subjects(self, subjects: list[Subject]) -> None:
        super()._apply_subjects(
            [subject for subject in subjects if is_trial_subject(subject.name)]
        )

    def _exam_service(self) -> ExamService:
        service = super()._exam_service()
        if self.current_subject is not None:
            try:
                allowed = self.test_workspace.exam_paths(self.current_subject)
            except (TypeError, ValueError) as exc:
                LOGGER.warning("Không thể mở đề AIL303M_t: %s", exc)
                service.questions = []
            else:
                if allowed is not None:
                    service.questions = [
                        question
                        for question in service.questions
                        if question.relative_path in allowed
                    ]
        return service

    def show_data_import(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục môn học có hậu tố _t"
        )
        if not selected:
            return
        try:
            self.test_workspace.install_from(Path(selected))
        except (OSError, TypeError, ValueError, SubjectManagementError) as exc:
            QMessageBox.warning(self, "Không thể thêm môn học", str(exc))
            return
        self.refresh_data()

    def show_settings(self, management: bool = False) -> None:
        super().show_settings(management)
        page = self._dynamic_page
        if isinstance(page, SettingsScreen):
            page.data_path.setReadOnly(True)
            path_layout = page.data_path.parentWidget().layout()
            if path_layout is not None:
                browse = path_layout.itemAt(1).widget()
                if browse is not None:
                    browse.setEnabled(False)

    def _save_settings(self, settings: AppSettings) -> None:
        settings.data_dir = str(self.test_workspace.data_dir)
        super()._save_settings(settings)
