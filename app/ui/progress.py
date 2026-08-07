from __future__ import annotations

from PyQt5.QtWidgets import QHBoxLayout, QProgressBar, QSizePolicy, QWidget


class StudyProgressBar(QProgressBar):
    """Thin, text-free progress bar used by Flashcard sessions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studyProgress")
        self.setTextVisible(False)
        self.setFixedHeight(8)
        self.setRange(0, 1)
        self.setValue(0)


class SegmentedProgressBar(QWidget):
    """One mini progress bar per Cramming round."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("segmentedProgressContainer")
        self.setFixedHeight(10)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(3)
        self.bars: list[QProgressBar] = []

    def set_progress(
        self,
        *,
        total_rounds: int,
        current_round: int,
        round_mastered: int,
        round_total: int,
        completed: bool = False,
    ) -> None:
        self._ensure_segments(max(0, total_rounds))
        for round_index, bar in enumerate(self.bars, start=1):
            if completed or round_index < current_round:
                state, maximum, value = "completed", 1, 1
                tooltip = f"Vòng {round_index}: hoàn thành"
            elif round_index == current_round:
                state = "current"
                maximum = max(1, round_total)
                value = min(maximum, max(0, round_mastered))
                tooltip = f"Vòng {round_index}: {value}/{round_total} câu đã làm đúng"
            else:
                state, maximum, value = "future", 1, 0
                tooltip = f"Vòng {round_index}: chưa học"
            bar.setProperty("segmentState", state)
            bar.setRange(0, maximum)
            bar.setValue(value)
            bar.setToolTip(tooltip)
            # Dynamic properties require repolishing for QSS selectors.
            bar.style().unpolish(bar)
            bar.style().polish(bar)
            bar.update()

    def _ensure_segments(self, amount: int) -> None:
        if len(self.bars) == amount:
            return
        while self.bars:
            bar = self.bars.pop()
            self._layout.removeWidget(bar)
            bar.deleteLater()
        for _ in range(amount):
            bar = QProgressBar()
            bar.setObjectName("segmentedProgress")
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._layout.addWidget(bar, 1)
            self.bars.append(bar)
