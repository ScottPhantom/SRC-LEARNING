from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.subject_management import SubjectInfo


class SubjectManagementPanel(QWidget):
    delete_requested = pyqtSignal(str)
    add_requested = pyqtSignal()
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("subjectManagementPanel")
        self._operation_message: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 24)
        layout.setSpacing(14)
        title = QLabel("Môn học đã cài")
        title.setObjectName("subjectManagementTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Quản lý thư mục DATA đã lưu trong tab Chung. Xóa môn sẽ chuyển dữ liệu "
            "vào vùng khôi phục; lịch sử học và thi vẫn được giữ."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("subjectManagementTable")
        self.table.setHorizontalHeaderLabels(
            ["Môn học", "Số câu", "Dung lượng", "Đường dẫn", "Trạng thái"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setTextElideMode(Qt.ElideMiddle)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.table.setMinimumHeight(120)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(70)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(1, 86)
        self.table.setColumnWidth(2, 118)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table)
        self.status_label = QLabel("Đang tải danh sách môn học…")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        actions = QHBoxLayout()
        self.add_button = QPushButton("Thêm / cập nhật môn")
        self.add_button.clicked.connect(self.add_requested)
        self.refresh_button = QPushButton("Làm mới")
        self.refresh_button.clicked.connect(self.refresh_requested)
        self.delete_button = QPushButton("Xóa môn đã chọn")
        self.delete_button.setProperty("danger", True)
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._request_delete)
        for button in (self.add_button, self.refresh_button, self.delete_button):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)

    def set_subjects(self, subjects: list[SubjectInfo]) -> None:
        self.table.setRowCount(0)
        for info in subjects:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                info.name,
                str(info.question_count),
                self._format_size(info.size_bytes),
                str(info.path),
                info.status,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
        self.delete_button.setEnabled(False)
        visible_rows = min(max(self.table.rowCount(), 1), 8)
        row_height = self.table.verticalHeader().defaultSectionSize()
        table_height = (
            self.table.horizontalHeader().sizeHint().height()
            + visible_rows * row_height
            + 2 * self.table.frameWidth()
            + 4
        )
        self.table.setFixedHeight(max(120, table_height))
        self.status_label.setText(
            self._operation_message
            or (f"{len(subjects)} môn học trong DATA." if subjects else "Chưa có môn học trong DATA.")
        )

    def show_operation_message(self, message: str) -> None:
        self._operation_message = message
        self.status_label.setText(message)

    @staticmethod
    def _format_size(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    def selected_subject(self) -> str | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.text() if item is not None else None

    def _selection_changed(self) -> None:
        self.delete_button.setEnabled(self.selected_subject() is not None)

    def _request_delete(self) -> None:
        name = self.selected_subject()
        if name:
            self.delete_requested.emit(name)
