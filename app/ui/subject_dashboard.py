from __future__ import annotations

from collections.abc import Mapping, Sequence
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
    QStackedWidget,
    QVBoxLayout,
)

from app.domain.models import LearningQuestionReview, WeakQuestionReview
from app.ui.image_viewer import QuestionImageViewer

ReviewEntry = LearningQuestionReview | WeakQuestionReview

BANK_CATEGORY_LABELS = {
    "Fill_blanks": "ĐIỀN KHUYẾT",
    "Selections_1_choose": "CHỌN MỘT",
    "Selections_Multiple_choose": "CHỌN NHIỀU",
    "True_False": "TRUE/FALSE",
}


class QuestionBankNotificationDialog(QDialog):
    """Modal, persistent slide viewer for one unseen question-bank version."""

    item_viewed = pyqtSignal(int)
    completion_requested = pyqtSignal()

    def __init__(
        self,
        subject: str,
        subject_path: Path,
        bank_version: int,
        items: Sequence[Mapping[str, object]],
        crop_region: tuple[float, float, float, float],
        parent=None,
    ):
        super().__init__(parent)
        if not items:
            raise ValueError("Question Bank Notification cần ít nhất một thay đổi")
        self.subject = subject
        self.subject_path = Path(subject_path)
        self.bank_version = bank_version
        self.items = [dict(item) for item in items]
        self.current_index = 0
        self.viewed_indices = {
            int(item["item_index"]) for item in self.items if item.get("viewed_at")
        }
        self._allow_close = False
        self._first_show = True

        self.setObjectName("questionBankNotificationDialog")
        self.setWindowTitle(f"Cập nhật Question Bank — {subject}")
        self.setWindowModality(Qt.ApplicationModal)
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setMinimumSize(820, 580)
        self.resize(980, 680)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(0)
        self.card = QFrame()
        self.card.setObjectName("bankNotificationCard")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(15, 23, 42, 80))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(10)
        self.position_label = QLabel()
        self.position_label.setObjectName("bankNotificationPosition")
        self.position_label.setAccessibleName("Vị trí thay đổi đang xem")
        header.addWidget(self.position_label)
        header.addStretch()
        self.version_label = QLabel(f"{subject} • BANK VERSION {bank_version}")
        self.version_label.setObjectName("bankNotificationVersion")
        self.version_label.setAccessibleName(
            f"Môn {subject}, phiên bản Question Bank {bank_version}"
        )
        header.addWidget(self.version_label)
        layout.addLayout(header)

        badges = QHBoxLayout()
        badges.setSpacing(8)
        self.change_badge = QLabel()
        self.change_badge.setObjectName("bankChangeBadge")
        self.change_badge.setAlignment(Qt.AlignCenter)
        self.change_badge.setAccessibleName("Loại thay đổi")
        badges.addWidget(self.change_badge)
        self.category_badge = QLabel()
        self.category_badge.setObjectName("bankCategoryBadge")
        self.category_badge.setAlignment(Qt.AlignCenter)
        self.category_badge.setAccessibleName("Loại câu hỏi")
        badges.addWidget(self.category_badge)
        badges.addStretch()
        layout.addLayout(badges)

        self.title_label = QLabel()
        self.title_label.setObjectName("bankNotificationTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setAccessibleName("Tiêu đề thay đổi Question Bank")
        layout.addWidget(self.title_label)
        self.detail_label = QLabel()
        self.detail_label.setObjectName("bankNotificationDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setAccessibleName("Chi tiết thay đổi Question Bank")
        layout.addWidget(self.detail_label)

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("bankNotificationContent")
        self.viewer = QuestionImageViewer()
        self.viewer.setObjectName("bankNotificationImageViewer")
        self.viewer.setAccessibleName("Ảnh mới nhất của câu hỏi")
        self.viewer.set_crop_region(crop_region)
        self.content_stack.addWidget(self.viewer)
        self.missing_frame = QFrame()
        self.missing_frame.setObjectName("bankMissingImagePlaceholder")
        missing_layout = QVBoxLayout(self.missing_frame)
        missing_layout.setContentsMargins(28, 28, 28, 28)
        missing_layout.addStretch()
        self.missing_title = QLabel("Ảnh câu hỏi không còn trong DATA")
        self.missing_title.setObjectName("bankMissingImageTitle")
        self.missing_title.setAlignment(Qt.AlignCenter)
        self.missing_title.setAccessibleName("Ảnh câu hỏi đã bị xóa")
        missing_layout.addWidget(self.missing_title)
        self.missing_metadata = QLabel()
        self.missing_metadata.setObjectName("bankMissingImageMetadata")
        self.missing_metadata.setAlignment(Qt.AlignCenter)
        self.missing_metadata.setWordWrap(True)
        missing_layout.addWidget(self.missing_metadata)
        missing_layout.addStretch()
        self.content_stack.addWidget(self.missing_frame)
        layout.addWidget(self.content_stack, 1)

        self.answer_card = QFrame()
        self.answer_card.setObjectName("bankAnswerCard")
        answer_layout = QHBoxLayout(self.answer_card)
        answer_layout.setContentsMargins(18, 12, 18, 12)
        self.answer_caption = QLabel()
        self.answer_caption.setObjectName("bankAnswerCaption")
        answer_layout.addWidget(self.answer_caption)
        answer_layout.addStretch()
        self.answer_label = QLabel()
        self.answer_label.setObjectName("bankAnswerValue")
        self.answer_label.setAccessibleName("Đáp án của câu hỏi")
        answer_layout.addWidget(self.answer_label)
        layout.addWidget(self.answer_card)

        self.error_label = QLabel()
        self.error_label.setObjectName("bankNotificationError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.previous_button = QPushButton("Trước")
        self.previous_button.setObjectName("bankPreviousButton")
        self.previous_button.setProperty("secondary", True)
        self.previous_button.setAccessibleName("Xem thay đổi trước")
        self.previous_button.setAutoDefault(False)
        self.previous_button.clicked.connect(self.show_previous)
        controls.addWidget(self.previous_button)
        self.next_button = QPushButton("Tiếp theo")
        self.next_button.setObjectName("bankNextButton")
        self.next_button.setAccessibleName("Xem thay đổi tiếp theo")
        self.next_button.setAutoDefault(False)
        self.next_button.clicked.connect(self.show_next)
        controls.addWidget(self.next_button)
        controls.addStretch()
        self.finish_button = QPushButton("Hoàn tất")
        self.finish_button.setObjectName("bankFinishButton")
        self.finish_button.setAccessibleName(
            "Hoàn tất xem cập nhật và không hiển thị lại phiên bản này"
        )
        self.finish_button.setAutoDefault(False)
        self.finish_button.clicked.connect(self._request_completion)
        controls.addWidget(self.finish_button)
        layout.addLayout(controls)

        self.setTabOrder(self.previous_button, self.next_button)
        self.setTabOrder(self.next_button, self.finish_button)
        self._navigation_shortcuts: list[QShortcut] = []
        for key, callback in (
            (Qt.Key_Left, self.show_previous),
            (Qt.Key_Right, self.show_next),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._navigation_shortcuts.append(shortcut)
        self._render_current()
        self._update_completion_state()

    @staticmethod
    def _display_answer(value: object) -> str:
        answer = str(value or "").strip()
        return " ".join(answer) if answer else "Chưa có"

    @staticmethod
    def _question_name(path_value: object) -> str:
        path = Path(str(path_value or "Câu hỏi"))
        return path.stem or "Câu hỏi"

    def _render_current(self) -> None:
        item = self.items[self.current_index]
        kind = str(item["change_type"])
        path_value = item.get("new_path") or item.get("old_path")
        question_name = self._question_name(path_value)
        category = str(item.get("new_category") or item.get("old_category") or "")
        category_label = BANK_CATEGORY_LABELS.get(category, category.upper())

        self.position_label.setText(
            f"Thay đổi {self.current_index + 1}/{len(self.items)}"
        )
        self.change_badge.setText(kind)
        self.change_badge.setProperty("changeType", kind)
        self.change_badge.style().unpolish(self.change_badge)
        self.change_badge.style().polish(self.change_badge)
        self.category_badge.setText(category_label)
        self.category_badge.setVisible(bool(category_label))

        if kind == "ADD":
            self.title_label.setText(f"Đã bổ sung {question_name}")
            self.detail_label.setText(f"THÊM MỚI • {category_label}")
            self.answer_caption.setText("Đáp án")
            self.answer_label.setText(self._display_answer(item.get("new_answer")))
        elif kind == "UPDATE":
            old_answer = self._display_answer(item.get("old_answer"))
            new_answer = self._display_answer(item.get("new_answer"))
            self.title_label.setText(f"{question_name} đã được cập nhật")
            self.detail_label.setText(f"Đáp án “{old_answer}” → “{new_answer}”")
            self.answer_caption.setText("Đáp án mới")
            self.answer_label.setText(new_answer)
        else:
            self.title_label.setText(f"{question_name} đã ngừng sử dụng")
            self.detail_label.setText(
                "Câu hỏi này đã được gỡ khỏi Question Bank hiện hành."
            )
            self.answer_caption.setText("Đáp án trước đây")
            self.answer_label.setText(self._display_answer(item.get("old_answer")))

        image_path = self.subject_path / str(path_value or "")
        if image_path.is_file():
            try:
                self.viewer.load_image(image_path, category=category)
                self.content_stack.setCurrentWidget(self.viewer)
            except ValueError:
                self._show_missing_image(item, category_label)
        else:
            self._show_missing_image(item, category_label)
        self.previous_button.setEnabled(self.current_index > 0)
        self.next_button.setEnabled(self.current_index < len(self.items) - 1)

    def _show_missing_image(
        self, item: Mapping[str, object], category_label: str
    ) -> None:
        old_path = str(item.get("old_path") or "Không có")
        old_answer = self._display_answer(item.get("old_answer"))
        self.missing_metadata.setText(
            f"Đường dẫn cũ: {old_path}\n"
            f"Loại câu: {category_label or 'Không có'}\n"
            f"Đáp án cũ: {old_answer}"
        )
        self.content_stack.setCurrentWidget(self.missing_frame)

    def _mark_current_viewed(self) -> None:
        item_index = int(self.items[self.current_index]["item_index"])
        if item_index not in self.viewed_indices:
            self.viewed_indices.add(item_index)
            self.item_viewed.emit(item_index)
        self._update_completion_state()

    def _update_completion_state(self) -> None:
        all_viewed = len(self.viewed_indices) == len(self.items)
        self.finish_button.setVisible(all_viewed)
        self.finish_button.setEnabled(all_viewed)

    def show_next(self) -> None:
        if self.current_index >= len(self.items) - 1:
            return
        self.current_index += 1
        self._render_current()
        self._mark_current_viewed()

    def show_previous(self) -> None:
        if self.current_index <= 0:
            return
        self.current_index -= 1
        self._render_current()
        self._mark_current_viewed()

    def _request_completion(self) -> None:
        if len(self.viewed_indices) != len(self.items):
            return
        self.finish_button.setEnabled(False)
        self.completion_requested.emit()

    def complete_and_close(self) -> None:
        self._allow_close = True
        super().accept()

    def show_completion_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()
        self.finish_button.setEnabled(True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            self._mark_current_viewed()
            self.next_button.setFocus(Qt.OtherFocusReason)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Right:
            self.show_next()
        elif event.key() == Qt.Key_Left:
            self.show_previous()
        elif event.key() in (Qt.Key_Escape, Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            pass
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def reject(self) -> None:
        if self._allow_close:
            super().reject()

    def closeEvent(self, event) -> None:
        if self._allow_close:
            super().closeEvent(event)
        else:
            event.ignore()


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
