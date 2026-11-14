from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


class DataImportDialog(QDialog):
    install_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._completed = False
        self.setObjectName("dataImportDialog")
        self.setWindowTitle("Thêm môn học")
        self.setWindowModality(Qt.ApplicationModal)
        self.setModal(True)
        self.setMinimumWidth(520)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("dataImportCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 22, 24, 22)
        card_layout.setSpacing(12)

        title = QLabel("Thêm dữ liệu môn học")
        title.setObjectName("dataImportTitle")
        card_layout.addWidget(title)

        description = QLabel(
            "Nhập Google Drive File ID hoặc link tải do quản trị viên cung cấp. "
            "SRC-LEARNING chỉ chấp nhận những gói đã được phê duyệt."
        )
        description.setObjectName("dataImportDescription")
        description.setWordWrap(True)
        card_layout.addWidget(description)

        self.code_input = QLineEdit()
        self.code_input.setObjectName("dataImportCodeInput")
        self.code_input.setPlaceholderText("Google Drive File ID hoặc link chia sẻ")
        self.code_input.setClearButtonEnabled(True)
        self.code_input.returnPressed.connect(self._submit)
        card_layout.addWidget(self.code_input)

        self.status_label = QLabel("Dữ liệu sẽ được kiểm tra trước khi cài đặt.")
        self.status_label.setObjectName("dataImportStatus")
        self.status_label.setWordWrap(True)
        card_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("dataImportProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        card_layout.addWidget(self.progress_bar)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = QPushButton("Hủy")
        self.cancel_button.setProperty("secondary", True)
        self.cancel_button.clicked.connect(self.reject)
        self.install_button = QPushButton("Tải và cài đặt")
        self.install_button.setObjectName("dataImportInstallButton")
        self.install_button.clicked.connect(self._submit)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.install_button)
        card_layout.addLayout(actions)

        outer.addWidget(card)
        self.code_input.setFocus()

    def _submit(self) -> None:
        if self._running or self._completed:
            return
        code = self.code_input.text().strip()
        if not code:
            self.show_error("Hãy nhập Google Drive File ID hoặc link chia sẻ.")
            self.code_input.setFocus()
            return
        self.install_requested.emit(code)

    def set_running(self, running: bool) -> None:
        self._running = running
        self.code_input.setEnabled(not running)
        self.install_button.setEnabled(not running)
        self.cancel_button.setEnabled(not running)
        if running:
            self.progress_bar.show()
            self.status_label.setProperty("error", False)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)

    def update_progress(self, stage: str, percent: int, message: str) -> None:
        del stage
        self.progress_bar.show()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(max(0, min(100, percent)))
        self.status_label.setText(message)
        self._fit_status_layout()

    def show_error(self, message: str) -> None:
        self.set_running(False)
        self.status_label.setProperty("error", True)
        self.status_label.setText(message)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self._fit_status_layout()

    def show_complete(self, message: str) -> None:
        self._completed = True
        self._running = False
        self.progress_bar.show()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.status_label.setProperty("error", False)
        self.status_label.setText(message)
        self.code_input.setEnabled(False)
        self.install_button.setText("Hoàn tất")
        self.install_button.setEnabled(True)
        try:
            self.install_button.clicked.disconnect()
        except TypeError:
            pass
        self.install_button.clicked.connect(self.accept)
        self.cancel_button.hide()
        self._fit_status_layout()

    def _fit_status_layout(self) -> None:
        # A wrapped QLabel can need more height than the dialog originally
        # allocated. adjustSize() may also limit the width to the screen;
        # recompute the wrapped height at that actual width, not sizeHint's.
        self.adjustSize()
        label = self.status_label
        label.setMinimumHeight(max(label.fontMetrics().height(), label.heightForWidth(label.width())))
        card = label.parentWidget()
        card.layout().invalidate()
        card.setMinimumHeight(card.minimumSizeHint().height())
        self.layout().invalidate()
        self.resize(self.width(), max(
            self.minimumSizeHint().height(),
            self.layout().totalHeightForWidth(self.width()),
        ))

    def reject(self) -> None:
        if self._running:
            return
        super().reject()
