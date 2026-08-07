from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.answer_options import AnswerOptionsWidget, refresh_style


class QuestionNavigationGrid(QWidget):
    """Lưới câu hỏi có trạng thái, thay thế danh sách điều hướng dạng dọc."""

    question_selected = pyqtSignal(int)

    def __init__(self, columns: int = 5, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.buttons: list[QPushButton] = []
        self._states: list[str] = []
        self._current = -1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("Câu hỏi (0 / 0)")
        self.summary.setObjectName("navigationSummary")
        layout.addWidget(self.summary)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("questionGridScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.container = QWidget()
        self.grid = QGridLayout(self.container)
        self.grid.setContentsMargins(0, 4, 4, 4)
        self.grid.setSpacing(7)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, 1)

    def set_count(self, total: int) -> None:
        if total == len(self.buttons):
            return
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.buttons = []
        self._states = ["unanswered"] * total
        self._current = -1
        for index in range(total):
            button = QPushButton(str(index + 1))
            button.setObjectName("questionNavButton")
            button.setFixedSize(42, 42)
            button.setCursor(Qt.PointingHandCursor)
            button.setProperty("navState", "unanswered")
            button.setProperty("current", False)
            button.setAccessibleName(f"Đi đến câu {index + 1}")
            button.clicked.connect(
                lambda _checked=False, target=index: self.question_selected.emit(target)
            )
            self.grid.addWidget(button, index // self.columns, index % self.columns)
            self.buttons.append(button)
        self.set_progress(0, total)

    def set_progress(self, answered: int, total: int | None = None) -> None:
        amount = len(self.buttons) if total is None else total
        self.summary.setText(f"Câu hỏi ({answered} / {amount})")

    def set_state(self, index: int, state: str) -> None:
        if not 0 <= index < len(self.buttons):
            return
        self._states[index] = state
        button = self.buttons[index]
        button.setProperty("navState", state)
        refresh_style(button)

    def set_current(self, index: int) -> None:
        previous = self._current
        self._current = index
        for target in {previous, index}:
            if 0 <= target < len(self.buttons):
                button = self.buttons[target]
                button.setProperty("current", target == index)
                refresh_style(button)

    def state(self, index: int) -> str:
        return self._states[index]

    def item(self, index: int) -> QPushButton:
        """Compatibility helper cho code/test từng truy cập ``navigator.item``."""
        return self.buttons[index]


class AssessmentSidebar(QFrame):
    """Sidebar dùng chung: đáp án, điều hướng câu hỏi và vùng action."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("assessmentSidebar")
        self.setMinimumWidth(270)
        self.setMaximumWidth(330)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        self.answer_group = QGroupBox("Đáp án")
        answer_layout = QVBoxLayout(self.answer_group)
        self.answer_options = AnswerOptionsWidget()
        answer_layout.addWidget(self.answer_options)
        layout.addWidget(self.answer_group)

        self.navigation = QuestionNavigationGrid()
        layout.addWidget(self.navigation, 1)

        separator = QFrame()
        separator.setObjectName("sidebarSeparator")
        separator.setFrameShape(QFrame.HLine)
        layout.addWidget(separator)

        self.actions = QVBoxLayout()
        self.actions.setSpacing(9)
        layout.addLayout(self.actions)

    def add_action(self, button: QPushButton) -> None:
        button.setMinimumHeight(42)
        self.actions.addWidget(button)

    def add_action_row(self, *buttons: QPushButton) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        for button in buttons:
            button.setMinimumHeight(42)
            row.addWidget(button)
        self.actions.addLayout(row)
