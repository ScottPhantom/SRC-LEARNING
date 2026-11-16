from __future__ import annotations

import threading
from pathlib import Path

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from app.services.data_package_installer import (
    DataInstallResult,
    DataPackageError,
    DataPackageInstaller,
)
from app.services.package_catalog_source import PackageCatalogSource


def _safe_emit(signal, *args) -> None:
    # Receiver may be deleted while the worker thread is still running.
    try:
        signal.emit(*args)
    except RuntimeError:
        pass


class DataInstallSignals(QObject):
    progress = pyqtSignal(str, int, str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)


class CatalogRefreshSignals(QObject):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)


class CatalogRefreshTask(QRunnable):
    def __init__(self, source: PackageCatalogSource):
        super().__init__()
        self.source = source
        self.signals = CatalogRefreshSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self.source.load()
        except (DataPackageError, OSError, RuntimeError, ValueError) as exc:
            _safe_emit(
                self.signals.failed, f"Không đọc được danh mục môn học: {exc}"
            )
            return
        _safe_emit(self.signals.completed, result)


class DataInstallTask(QRunnable):
    def __init__(
        self,
        installer: DataPackageInstaller,
        code: str,
        data_dir: Path,
        *,
        replace_existing: bool,
    ):
        super().__init__()
        self.installer = installer
        self.code = code
        self.data_dir = Path(data_dir)
        self.replace_existing = replace_existing
        self.cancelled = threading.Event()
        self.signals = DataInstallSignals()

    def _report(self, stage: str, percent: int, message: str) -> None:
        _safe_emit(self.signals.progress, stage, percent, message)

    @pyqtSlot()
    def run(self) -> None:
        try:
            result: DataInstallResult = self.installer.install(
                self.code,
                self.data_dir,
                replace_existing=self.replace_existing,
                progress=self._report,
                cancelled=self.cancelled.is_set,
            )
        except DataPackageError as exc:
            _safe_emit(self.signals.failed, str(exc))
            return
        except (OSError, RuntimeError, ValueError) as exc:
            _safe_emit(self.signals.failed, f"Không thể cài đặt dữ liệu: {exc}")
            return
        _safe_emit(self.signals.completed, result)
