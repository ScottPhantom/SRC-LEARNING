from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from app.services.data_scanner import DataScannerService


class ScanSignals(QObject):
    completed = pyqtSignal(object, object)
    failed = pyqtSignal(object, str)


class ScanTask(QRunnable):
    def __init__(self, data_dir: Path):
        super().__init__()
        self.data_dir = data_dir
        self.signals = ScanSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            subjects = DataScannerService(self.data_dir).scan()
        except (OSError, RuntimeError, ValueError) as exc:
            try:
                self.signals.failed.emit(self.data_dir, str(exc))
            except RuntimeError:
                pass
            return
        try:
            self.signals.completed.emit(self.data_dir, subjects)
        except RuntimeError:
            pass
