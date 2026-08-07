from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QGridLayout, QLabel, QPushButton, QSizePolicy, QWidget

from app.domain.models import Question, normalize_answer


def refresh_style(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class AnswerOptionButton(QPushButton):
    """Nút đáp án bo góc có nhãn phím tắt ở góc trên-phải."""

    def __init__(self, option: str, shortcut_number: int, parent=None):
        super().__init__(option, parent)
        self.option = option
        self.setObjectName("answerOptionButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(72, 58)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName(f"Đáp án {option}, phím {shortcut_number}")
        self.shortcut_hint = QLabel(str(shortcut_number), self)
        self.shortcut_hint.setObjectName("answerShortcutHint")
        self.shortcut_hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.shortcut_hint.adjustSize()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.shortcut_hint.adjustSize()
        self.shortcut_hint.move(
            self.width() - self.shortcut_hint.width() - 8,
            6,
        )


class AnswerOptionsWidget(QWidget):
    """Lưới đáp án dùng chung cho Mock Exam và Cramming."""

    selection_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(10)
        self._layout.setVerticalSpacing(10)
        self.option_widgets: list[AnswerOptionButton] = []
        self._question: Question | None = None

    def set_question(
        self,
        question: Question,
        *,
        selected_answer: str = "",
        read_only: bool = False,
        correct_answer: str = "",
        show_feedback: bool = False,
    ) -> None:
        self._clear()
        self._question = question
        selected = set(normalize_answer(selected_answer))
        correct = set(normalize_answer(correct_answer))
        for index, option in enumerate(question.options):
            button = AnswerOptionButton(option, index + 1, self)
            button.setChecked(option in selected)
            button.setEnabled(not read_only)
            state = "neutral"
            if show_feedback:
                if option in correct:
                    state = "correct"
                elif option in selected:
                    state = "wrong"
            button.setProperty("answerState", state)
            button.clicked.connect(
                lambda checked, current=button: self._option_clicked(current, checked)
            )
            self._layout.addWidget(button, index // 2, index % 2)
            self.option_widgets.append(button)

    def selected_answer(self) -> str:
        return normalize_answer(
            "".join(button.option for button in self.option_widgets if button.isChecked())
        )

    def toggle_option(self, option: str) -> bool:
        """Toggle một lựa chọn từ chuột hoặc keymap; bỏ qua nút không tồn tại."""
        normalized = option.upper()
        for button in self.option_widgets:
            if button.option == normalized and button.isEnabled():
                button.click()
                return True
        return False

    def show_feedback(
        self, question: Question, selected_answer: str, correct_answer: str
    ) -> None:
        self.set_question(
            question,
            selected_answer=selected_answer,
            read_only=True,
            correct_answer=correct_answer,
            show_feedback=True,
        )

    def _option_clicked(self, clicked: AnswerOptionButton, checked: bool) -> None:
        if checked and self._question is not None and not self._question.is_multiple:
            for button in self.option_widgets:
                if button is not clicked and button.isChecked():
                    button.setChecked(False)
                    refresh_style(button)
        refresh_style(clicked)
        self.selection_changed.emit(self.selected_answer())

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.option_widgets = []
