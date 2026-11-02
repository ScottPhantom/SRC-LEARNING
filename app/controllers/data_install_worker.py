from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from app.services.data_package_installer import (
    DataInstallResult,
    DataPackageError,
    DataPackageInstaller,
)


class DataInstallSignals(QObject):
    progress = pyqtSignal(str, int, str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)


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
        self.signals = DataInstallSignals()

    def _report(self, stage: str, percent: int, message: str) -> None:
        try:
            self.signals.progress.emit(stage, percent, message)
        except RuntimeError:
            pass

    @pyqtSlot()
    def run(self) -> None:
        try:
            result: DataInstallResult = self.installer.install(
                self.code,
                self.data_dir,
                replace_existing=self.replace_existing,
                progress=self._report,
            )
        except DataPackageError as exc:
            try:
                self.signals.failed.emit(str(exc))
            except RuntimeError:
                pass
            return
        except (OSError, RuntimeError, ValueError) as exc:
            try:
                self.signals.failed.emit(f"Không thể cài đặt dữ liệu: {exc}")
            except RuntimeError:
                pass
            return
        try:
            self.signals.completed.emit(result)
        except RuntimeError:
            pass
