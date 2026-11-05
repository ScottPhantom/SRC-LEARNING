"""Fresh, temporary learning state for one Colab notebook run."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

from app.config import catalog_csv_url
from app.domain.models import Subject
from app.repositories.answer_key import AnswerKeyReport, AnswerKeyRepository
from app.repositories.database import Database
from app.services.data_package_installer import DataInstallResult, DataPackageInstaller
from app.services.data_scanner import DataScannerService
from app.services.package_catalog_source import PackageCatalogSource


class MobileLearningSession:
    """Keep downloaded subjects and progress isolated from desktop data."""

    def __init__(
        self,
        root: Path | None = None,
        installer: DataPackageInstaller | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else Path(
            tempfile.mkdtemp(prefix="src-learning-colab-")
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.root / "DATA"
        self.data_dir.mkdir(exist_ok=True)
        self.database = Database(self.root / "study_progress.sqlite3")
        self._installer = installer
        self.subjects: dict[str, Subject] = {}
        self.answer_reports: dict[str, AnswerKeyReport] = {}

    def install_subject(
        self,
        code: str,
        progress: Callable[[str, int, str], None] | None = None,
    ) -> DataInstallResult:
        if self._installer is None:
            catalog = PackageCatalogSource(
                catalog_csv_url(), self.root / "catalog.csv"
            ).load()
            installer = DataPackageInstaller(catalog.catalog)
        else:
            installer = self._installer
        result = installer.install(code, self.data_dir, progress=progress)
        self.refresh_subjects()
        return result

    def refresh_subjects(self) -> None:
        scanned = DataScannerService(self.data_dir).scan()
        self.database.sync_questions(
            [question for subject in scanned for question in subject.questions],
            [subject.name for subject in scanned],
        )
        self.subjects = {subject.name: subject for subject in scanned}
        self.answer_reports = {
            subject.name: AnswerKeyRepository().load(subject.path, subject.questions)
            for subject in scanned
        }

    def close(self) -> None:
        self.database.close()
