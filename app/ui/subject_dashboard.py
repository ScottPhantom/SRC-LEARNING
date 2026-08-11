from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPointF,
    QPropertyAnimation,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QKeySequence
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QShortcut,
    QVBoxLayout,
)

from app.domain.models import LearningQuestionReview, WeakQuestionReview
from app.ui.image_viewer import QuestionImageViewer

ReviewEntry = LearningQuestionReview | WeakQuestionReview


class StudyModeCard(QFrame):
    """Card vuông có thể click với animation kích thước và đổ bóng."""

    clicked = pyqtSignal(str)
    hover_changed = pyqtSignal(str, bool)
    BASE_SIZE = QSize(264, 264)
    HOVER_SIZE = QSize(317, 317)

    def __init__(
        self,
        mode: str,
        icon: str,
        title: str,
        description: str,
        parent=None,
    ):
        super().__init__(parent)
        self.mode = mode
        self.setObjectName("studyModeCard")
        self.setProperty("hovered", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"Mở chế độ {title}")
        self.setMinimumSize(self.BASE_SIZE)
        self.setMaximumSize(self.BASE_SIZE)
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(22)
        self.shadow.setOffset(0, 8)
        self.shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(self.shadow)
        self._animation: QParallelAnimationGroup | None = None
        self._dim_animation: QPropertyAnimation | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(10)
        layout.addStretch()
        self.focus_overlay = QFrame(self)
        self.focus_overlay.setObjectName("studyModeFocusOverlay")
        self.focus_overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.focus_overlay.setGeometry(self.rect())
        self.focus_overlay_effect = QGraphicsOpacityEffect(self.focus_overlay)
        self.focus_overlay_effect.setOpacity(0.0)
        self.focus_overlay.setGraphicsEffect(self.focus_overlay_effect)
        self.focus_overlay.hide()
        self.icon_label = QLabel(icon)
        self.icon_label.setObjectName("studyModeIcon")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("studyModeTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.description_label = QLabel(description)
        self.description_label.setObjectName("studyModeDescription")
        self.description_label.setAlignment(Qt.AlignCenter)
        self.description_label.setWordWrap(True)
        for label in (
            self.icon_label,
            self.title_label,
            self.description_label,
        ):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(label)
        layout.addStretch()

    def _set_hovered(self, hovered: bool) -> None:
        self.setProperty("hovered", hovered)
        self.style().unpolish(self)
        self.style().polish(self)
        if self._animation is not None:
            self._animation.stop()
        target_size = self.HOVER_SIZE if hovered else self.BASE_SIZE
        target_blur = 55.0 if hovered else 22.0
        target_offset = QPointF(0, 15 if hovered else 8)
        target_color = QColor(0, 0, 0, 175 if hovered else 90)
        group = QParallelAnimationGroup(self)
        for property_name, start, end in (
            (b"minimumSize", self.minimumSize(), target_size),
            (b"maximumSize", self.maximumSize(), target_size),
            (b"blurRadius", self.shadow.blurRadius(), target_blur),
            (b"offset", self.shadow.offset(), target_offset),
            (b"color", self.shadow.color(), target_color),
        ):
            target = (
                self.shadow
                if property_name in {b"blurRadius", b"offset", b"color"}
                else self
            )
            animation = QPropertyAnimation(target, property_name, group)
            animation.setStartValue(start)
            animation.setEndValue(end)
            animation.setDuration(240)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(animation)
        self._animation = group
        group.start()

    def enterEvent(self, event) -> None:
        self._set_hovered(True)
        self.hover_changed.emit(self.mode, True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_hovered(False)
        self.hover_changed.emit(self.mode, False)
        super().leaveEvent(event)

    def set_dimmed(self, dimmed: bool) -> None:
        if self._dim_animation is not None:
            self._dim_animation.stop()
        if dimmed:
            self.focus_overlay.show()
            self.focus_overlay.raise_()
        animation = QPropertyAnimation(
            self.focus_overlay_effect,
            b"opacity",
            self,
        )
        animation.setStartValue(self.focus_overlay_effect.opacity())
        animation.setEndValue(0.5 if dimmed else 0.0)
        animation.setDuration(240)
        animation.setEasingCurve(QEasingCurve.InOutCubic)
        if not dimmed:
            animation.finished.connect(self.focus_overlay.hide)
        self._dim_animation = animation
        animation.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.focus_overlay.setGeometry(self.rect())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit(self.mode)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit(self.mode)
            event.accept()
            return
        super().keyPressEvent(event)


class QuickReviewDialog(QDialog):
    rating_requested = pyqtSignal(str, bool)

    def __init__(
        self,
        reviews: list[ReviewEntry],
        current_index: int,
        crop_region: tuple[float, float, float, float],
        allow_rating: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        if not reviews:
            raise ValueError("Quick Review cần ít nhất một câu hỏi")
        self.reviews = list(reviews)
        self.current_index = max(0, min(current_index, len(self.reviews) - 1))
        self.review = self.reviews[self.current_index]
        self.setObjectName("quickReviewDialog")
        self.setModal(False)
        self.resize(900, 620)
        self.setMinimumSize(720, 500)
        layout = QVBoxLayout(self)
        self.heading = QLabel()
        self.heading.setObjectName("quickReviewTitle")
        layout.addWidget(self.heading)
        self.viewer = QuestionImageViewer()
        self.viewer.set_crop_region(crop_region)
        layout.addWidget(self.viewer, 1)
        answer_caption = QLabel("Đáp án đúng")
        answer_caption.setObjectName("quickReviewCaption")
        answer_caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(answer_caption)
        self.answer_label = QLabel()
        self.answer_label.setObjectName("quickReviewAnswer")
        self.answer_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.answer_label)
        actions = QHBoxLayout()
        self.known_button: QPushButton | None = None
        self.learning_button: QPushButton | None = None
        if allow_rating:
            self.known_button = QPushButton("Đã thuộc")
            self.known_button.setObjectName("quickReviewKnownButton")
            self.known_button.clicked.connect(lambda: self._rate_current(True))
            actions.addWidget(self.known_button)
            self.learning_button = QPushButton("Chưa thuộc")
            self.learning_button.setObjectName("quickReviewLearningButton")
            self.learning_button.setProperty("danger", True)
            self.learning_button.clicked.connect(lambda: self._rate_current(False))
            actions.addWidget(self.learning_button)
        actions.addStretch()
        self.close_button = QPushButton("Đóng")
        self.close_button.setProperty("secondary", True)
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)

        self._navigation_shortcuts: list[QShortcut] = []
        for key, callback in (
            (Qt.Key_Left, self.show_previous),
            (Qt.Key_Right, self.show_next),
            (Qt.Key_Space, self.close),
            (Qt.Key_Return, self.close),
            (Qt.Key_Enter, self.close),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(callback)
            self._navigation_shortcuts.append(shortcut)
        self._render_current()

    def _rate_current(self, known: bool) -> None:
        question_id = self.review.question.id
        self.rating_requested.emit(question_id, known)
        if known:
            del self.reviews[self.current_index]
            if not self.reviews:
                self.close()
                return
            self.current_index = min(self.current_index, len(self.reviews) - 1)
            self._render_current()
            return
        if self.current_index >= len(self.reviews) - 1:
            self.close()
            return
        self.current_index += 1
        self._render_current()

    def _render_current(self) -> None:
        self.review = self.reviews[self.current_index]
        filename = Path(self.review.question.relative_path).name
        position = f"{self.current_index + 1}/{len(self.reviews)}"
        self.setWindowTitle(f"Ôn tập nhanh — {filename} ({position})")
        self.heading.setText(f"{filename}  •  {position}")
        self.viewer.load_image(
            self.review.question.absolute_path,
            category=self.review.question.category,
        )
        self.answer_label.setText(self.review.correct_answer or "Chưa có đáp án")

    def show_next(self) -> None:
        if self.current_index >= len(self.reviews) - 1:
            return
        self.current_index += 1
        self._render_current()

    def show_previous(self) -> None:
        if self.current_index <= 0:
            return
        self.current_index -= 1
        self._render_current()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Right:
            self.show_next()
        elif event.key() == Qt.Key_Left:
            self.show_previous()
        elif event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.close()
        else:
            super().keyPressEvent(event)
            return
        event.accept()
