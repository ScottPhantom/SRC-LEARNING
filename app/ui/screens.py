from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PyQt5.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QCursor,
    QKeySequence,
    QLinearGradient,
    QPainter,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QShortcut,
    QSizePolicy,
    QSpacerItem,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import CATEGORIES, CATEGORY_LABELS
from app.domain.models import (
    AppSettings,
    ExamConfig,
    FeedbackMode,
    LearningQuestionReview,
    Question,
    Subject,
    WeakQuestionReview,
)
from app.repositories.answer_key import AnswerKeyReport
from app.services.exam import ExamResult, ExamService, ExamSession
from app.services.study import CrammingService, CramState, FlashcardService, FlashState
from app.ui.assessment_sidebar import AssessmentSidebar
from app.ui.background import AppBackgroundCanvas, paint_app_background
from app.ui.icons import create_line_icon
from app.ui.image_viewer import QuestionImageViewer
from app.ui.progress import SegmentedProgressBar, StudyProgressBar
from app.ui.status_capsule import StatusCapsule
from app.ui.subject_card import SubjectCard
from app.ui.subject_dashboard import QuickReviewDialog, StudyModeCard


def secondary(button: QPushButton) -> QPushButton:
    button.setProperty("secondary", True)
    return button


def page_title(text: str, subtitle: str = "") -> tuple[QLabel, QLabel]:
    title = QLabel(text)
    title.setObjectName("title")
    description = QLabel(subtitle)
    description.setObjectName("subtitle")
    description.setWordWrap(True)
    return title, description


OPTION_KEY_MAP = {
    **{Qt.Key_1 + index: option for index, option in enumerate("ABCDEFGH")},
    **{Qt.Key_A + index: option for index, option in enumerate("ABCDEFGH")},
}


def install_assessment_keymap(
    owner: QWidget,
    toggle_option: Callable[[str], bool],
    submit: Callable[[], None],
    previous: Callable[[], None],
    next_question: Callable[[], None],
) -> list[QShortcut]:
    """Cài keymap cấp màn hình để hoạt động dù focus đang ở widget con."""
    bindings: list[tuple[int, Callable[[], object]]] = [
        (key, lambda option=option: toggle_option(option))
        for key, option in OPTION_KEY_MAP.items()
    ]
    bindings.extend(
        [
            (Qt.Key_Return, submit),
            (Qt.Key_Enter, submit),
            (Qt.Key_Left, previous),
            (Qt.Key_Right, next_question),
        ]
    )
    shortcuts: list[QShortcut] = []
    for key, callback in bindings:
        shortcut = QShortcut(QKeySequence(key), owner)
        shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        shortcut.activated.connect(callback)
        shortcuts.append(shortcut)
    return shortcuts


class BrandButton(QPushButton):
    """Nút thương hiệu 'SRC Learning' ở góc trên-trái AppHeader với sizeHint chuẩn."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("globalHomeButton")
        self.setFlat(True)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setToolTip("Về màn hình chính")
        self.setAccessibleName("Về màn hình chính — SRC Learning")
        self.setText("SRC Learning")
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.setFixedHeight(38)
        self.update_theme()

    def update_theme(self) -> None:
        app = QApplication.instance()
        is_dark = (app and app.property("appliedTheme") == "dark")
        icon_color = QColor("#60A5FA") if is_dark else QColor("#0A84FF")
        self.setIcon(create_line_icon("logo", size=22, color=icon_color, stroke_width=2.0))
        self.setIconSize(QSize(22, 22))


class AnimatedHeaderActionButton(QPushButton):
    """Nút action có hiệu ứng hover 3D nhưng không làm giật bố cục header."""

    BASE_SIZE = QSize(36, 36)
    HOVER_SIZE = QSize(38, 38)

    def __init__(self, tooltip: str, parent=None):
        super().__init__(parent)
        self.setObjectName("headerActionButton")
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setMinimumSize(self.BASE_SIZE)
        self.setMaximumSize(self.BASE_SIZE)
        self._hover_background = QColor(0, 0, 0, 0)
        self._hover_animation: QParallelAnimationGroup | None = None
        self._icon_type: str | None = None
        self._base_icon_color = QColor("#515154")
        self._showing_hover_icon = False
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(8)
        self.shadow.setOffset(0, 2)
        self.shadow.setColor(QColor(96, 165, 250, 0))
        self.setGraphicsEffect(self.shadow)

    def _get_hover_background(self) -> QColor:
        return self._hover_background

    def _set_hover_background(self, color: QColor) -> None:
        self._hover_background = QColor(color)
        showing_hover_icon = color.alpha() > 16
        if self._icon_type is not None and showing_hover_icon != self._showing_hover_icon:
            self._showing_hover_icon = showing_hover_icon
            icon_color = QColor("#FFFFFF") if showing_hover_icon else self._base_icon_color
            self.setIcon(
                create_line_icon(
                    self._icon_type,
                    size=24,
                    color=icon_color,
                    stroke_width=2.0,
                )
            )
            self.setIconSize(QSize(24, 24))
        self.update()

    def set_action_icon(self, icon_type: str, color: QColor) -> None:
        self._icon_type = icon_type
        self._base_icon_color = QColor(color)
        icon_color = QColor("#FFFFFF") if self._showing_hover_icon else color
        self.setIcon(
            create_line_icon(icon_type, size=24, color=icon_color, stroke_width=2.0)
        )
        self.setIconSize(QSize(24, 24))

    hoverBackground = pyqtProperty(
        QColor,
        fget=_get_hover_background,
        fset=_set_hover_background,
    )

    def _animate_hover(self, hovered: bool) -> None:
        if self._hover_animation is not None:
            self._hover_animation.stop()
        target_size = self.HOVER_SIZE if hovered else self.BASE_SIZE
        target_background = (
            QColor(239, 65, 54, 255)
            if hovered
            else QColor(0, 0, 0, 0)
        )
        group = QParallelAnimationGroup(self)
        targets = (
            (self, b"minimumSize", self.minimumSize(), target_size),
            (self, b"maximumSize", self.maximumSize(), target_size),
            (self, b"hoverBackground", self.hoverBackground, target_background),
            (self.shadow, b"blurRadius", self.shadow.blurRadius(), 22.0 if hovered else 8.0),
            (self.shadow, b"offset", self.shadow.offset(), QPointF(0, 5 if hovered else 2)),
            (
                self.shadow,
                b"color",
                self.shadow.color(),
                QColor(239, 65, 54, 145 if hovered else 0),
            ),
        )
        for target, property_name, start_value, end_value in targets:
            animation = QPropertyAnimation(target, property_name, group)
            animation.setStartValue(start_value)
            animation.setEndValue(end_value)
            animation.setDuration(200)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(animation)
        self._hover_animation = group
        group.start()

    def enterEvent(self, event) -> None:
        self._animate_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_hover(False)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        if self._hover_background.alpha() > 0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            opacity = self._hover_background.alpha()
            gradient.setColorAt(0.0, QColor(239, 65, 54, opacity))
            gradient.setColorAt(1.0, QColor(251, 176, 64, opacity))
            painter.setBrush(gradient)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 11, 11)
            painter.end()
        super().paintEvent(event)


class AppHeader(QFrame):
    """Header nhận diện và điều hướng dùng chung cho toàn ứng dụng."""

    home_requested = pyqtSignal()
    history_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("globalHeader")
        self.setFixedHeight(62)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 8, 24, 8)
        layout.setSpacing(12)

        # Brand Button hiển thị đầy đủ icon + "SRC Learning" không bị clipped
        self.home_button = BrandButton()
        self.home_button.clicked.connect(self.home_requested)
        self.title_label = self.home_button  # Dành cho backward compatibility trong test

        layout.addWidget(self.home_button, alignment=Qt.AlignVCenter)
        layout.addStretch(1)

        # Right Action Capsule căn giữa dọc (Qt.AlignVCenter)
        self.action_capsule = QFrame()
        self.action_capsule.setObjectName("headerActionCapsule")
        capsule_layout = QHBoxLayout(self.action_capsule)
        capsule_layout.setContentsMargins(6, 3, 6, 3)
        capsule_layout.setSpacing(4)
        capsule_layout.setAlignment(Qt.AlignCenter)

        self.history_button = AnimatedHeaderActionButton("Lịch sử thi")
        self.history_button.setIconSize(QSize(24, 24))
        self.history_button.clicked.connect(self.history_requested)

        self.refresh_button = AnimatedHeaderActionButton("Làm mới dữ liệu")
        self.refresh_button.setIconSize(QSize(24, 24))
        self.refresh_button.clicked.connect(self.refresh_requested)

        self.settings_button = AnimatedHeaderActionButton("Cài đặt")
        self.settings_button.setIconSize(QSize(24, 24))
        self.settings_button.clicked.connect(self.settings_requested)

        capsule_layout.addWidget(self.history_button, alignment=Qt.AlignCenter)
        capsule_layout.addWidget(self.refresh_button, alignment=Qt.AlignCenter)
        capsule_layout.addWidget(self.settings_button, alignment=Qt.AlignCenter)

        layout.addWidget(self.action_capsule, alignment=Qt.AlignVCenter)
        self.is_home_mode = True
        self.set_home_mode(True)
        self.update_theme()

    def update_theme(self) -> None:
        app = QApplication.instance()
        is_dark = (app and app.property("appliedTheme") == "dark")
        icon_color = QColor("#A1A1A6") if is_dark else QColor("#515154")

        self.home_button.update_theme()
        self.history_button.set_action_icon("history", icon_color)
        self.refresh_button.set_action_icon("refresh", icon_color)
        self.settings_button.set_action_icon("settings", icon_color)
        self.style().unpolish(self)
        self.style().polish(self)
        self.action_capsule.style().unpolish(self.action_capsule)
        self.action_capsule.style().polish(self.action_capsule)
        self.update()

    def set_home_mode(self, is_home: bool) -> None:
        """Ẩn/hiện nhóm nút toolbar khi chuyển màn hình và cập nhật hiệu ứng glass header."""
        self.is_home_mode = is_home
        self.action_capsule.setVisible(is_home)
        self.setProperty("homeMode", "true" if is_home else "false")
        self.action_capsule.setProperty("homeMode", "true" if is_home else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.action_capsule.style().unpolish(self.action_capsule)
        self.action_capsule.style().polish(self.action_capsule)
        self.update()






class BasePage(QWidget):
    back_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        paint_app_background(painter, QRectF(self.rect()))
        painter.end()

    def update_theme(self) -> None:
        self.update()

    def back_button(self) -> QPushButton:
        button = secondary(QPushButton("← Quay lại"))
        button.clicked.connect(self.back_requested)
        return button


class HomeBackgroundCanvas(AppBackgroundCanvas):
    """Canvas dành riêng cho HomeScreen kết hợp ảnh gradient pastel ở Light Mode và shared dark background ở Dark Mode."""

    def __init__(self, parent=None):
        super().__init__(parent, variant="home")
        self.setObjectName("homeCanvas")
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:
        app = QApplication.instance()
        is_dark = (app and app.property("appliedTheme") == "dark")

        # Nếu AppShell cha đang vẽ continuous home background phía sau (ở Light Mode),
        # canvas con để trong suốt (WA_OpaquePaintEvent=False) để tránh vẽ đè.
        parent = self.parent()
        is_shell_painting = False
        while parent is not None:
            if getattr(parent, "home_background_active", False) and not is_dark:
                is_shell_painting = True
                break
            parent = parent.parent()

        if is_shell_painting:
            return

        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        paint_app_background(painter, QRectF(self.rect()), dark=is_dark, variant="home")
        painter.end()


class HomeScreen(QWidget):
    subject_selected = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    history_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("homePage")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._subjects_list: list[Subject] = []
        self._card_widgets: dict[str, SubjectCard] = {}
        self._current_data_dir: Path = Path("DATA")
        self._current_cols = 0

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ScrollArea với nền trong suốt hoàn toàn
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("homeScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setAttribute(Qt.WA_TranslucentBackground, True)
        self.scroll_area.setAutoFillBackground(False)

        viewport = self.scroll_area.viewport()
        if viewport:
            viewport.setObjectName("homeViewport")
            viewport.setAttribute(Qt.WA_TranslucentBackground, True)
            viewport.setAutoFillBackground(False)

        # Canvas chứa nền Ambient Glow
        self.canvas = HomeBackgroundCanvas()
        self.canvas_layout = QVBoxLayout(self.canvas)
        self.canvas_layout.setContentsMargins(76, 64, 76, 48)
        self.canvas_layout.setSpacing(0)

        # Content container max-width 1680px, căn trái
        self.content_container = QWidget()
        self.content_container.setObjectName("homeContentContainer")
        self.content_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.content_container.setMaximumWidth(1680)
        self.content_container.setAttribute(Qt.WA_TranslucentBackground, True)
        self.content_container.setAutoFillBackground(False)

        container_layout = QVBoxLayout(self.content_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        # Heading section (Title -> Subtitle -> Status Capsule)
        self.title_label = QLabel("Thư viện")
        self.title_label.setObjectName("homeTitle")

        self.subtitle_label = QLabel("Chọn một môn học để bắt đầu ôn luyện.")
        self.subtitle_label.setObjectName("homeSubtitle")

        self.status_capsule = StatusCapsule()
        self.status_capsule.settings_clicked.connect(self.settings_requested)
        self.notice = self.status_capsule  # Backward compatibility

        container_layout.addWidget(self.title_label)
        container_layout.addSpacing(10)  # Title -> Subtitle 10px
        container_layout.addWidget(self.subtitle_label)
        container_layout.addSpacing(22)  # Subtitle -> Status Capsule 22px
        container_layout.addWidget(self.status_capsule, alignment=Qt.AlignLeft)
        container_layout.addSpacing(42)  # Status Capsule -> Grid 42px

        # Grid Widget chứa Subject Cards
        self.cards_widget = QWidget()
        self.cards_widget.setObjectName("homeCardsContainer")
        self.cards_widget.setAttribute(Qt.WA_TranslucentBackground, True)
        self.cards_widget.setAutoFillBackground(False)
        self.cards_grid = QGridLayout(self.cards_widget)
        self.cards_grid.setContentsMargins(0, 0, 0, 0)
        self.cards_grid.setHorizontalSpacing(24)
        self.cards_grid.setVerticalSpacing(24)
        self.cards_grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        container_layout.addWidget(self.cards_widget)
        container_layout.addStretch(1)

        self.canvas_layout.addWidget(self.content_container, alignment=Qt.AlignLeft | Qt.AlignTop)
        self.canvas_layout.addStretch(1)

        self.scroll_area.setWidget(self.canvas)
        root_layout.addWidget(self.scroll_area)

        # Timer debounce cho resizeEvent
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(40)
        self._resize_timer.timeout.connect(self._reflow_grid)

    def set_subjects(self, subjects: list[Subject], data_dir: Path) -> None:
        self._subjects_list = subjects
        self._current_data_dir = data_dir

        # Xóa các card cũ không thuộc danh sách môn học
        new_names = {s.name for s in subjects}
        for name in list(self._card_widgets.keys()):
            if name not in new_names:
                card = self._card_widgets.pop(name)
                card.deleteLater()

        # Cập nhật hoặc khởi tạo SubjectCard mà không hủy object cũ
        for subject in subjects:
            if subject.name in self._card_widgets:
                self._card_widgets[subject.name].set_subject(subject)
            else:
                card = SubjectCard(subject)
                card.selected.connect(self.subject_selected.emit)
                self._card_widgets[subject.name] = card

        if not subjects:
            if not data_dir.exists():
                self.status_capsule.set_missing_dir(data_dir)
            else:
                self.status_capsule.set_empty(data_dir)
        else:
            self.status_capsule.set_data_ready(len(subjects), data_dir)

        self._reflow_grid(force=True)

    def set_loading(self, data_dir: Path) -> None:
        self.status_capsule.set_loading(data_dir)

    def update_theme(self) -> None:
        self.canvas.update()
        self.status_capsule.update_theme()
        for card in self._card_widgets.values():
            card.update_theme()

    def _reflow_grid(self, force: bool = False) -> None:
        if not self._subjects_list:
            while self.cards_grid.count():
                self.cards_grid.takeAt(0)
            return

        viewport_w = self.scroll_area.viewport().width()
        if viewport_w <= 1280:
            margin_h = 76
        elif viewport_w <= 1600:
            margin_h = 100
        else:
            margin_h = 140

        self.canvas_layout.setContentsMargins(margin_h, 64, margin_h, 48)

        available_w = min(viewport_w - (margin_h * 2), 1680)
        cols = max(1, min(4, (available_w + 24) // 444))

        if cols == self._current_cols and not force:
            return

        self._current_cols = cols

        # Gỡ bỏ các card cũ khỏi layout grid mà KHÔNG delete object
        while self.cards_grid.count():
            self.cards_grid.takeAt(0)

        # Thêm lại chính các SubjectCard widget cũ vào vị trí grid mới
        for idx, subject in enumerate(self._subjects_list):
            card = self._card_widgets.get(subject.name)
            if card:
                row = idx // cols
                col = idx % cols
                self.cards_grid.addWidget(card, row, col, Qt.AlignLeft | Qt.AlignTop)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_timer.start()


class ModeScreen(BasePage):
    mode_selected = pyqtSignal(str)
    learning_status_changed = pyqtSignal(str, bool)

    def __init__(
        self,
        subject: Subject,
        report: AnswerKeyReport,
        card_stats: dict[str, int],
        weak_questions: Mapping[str, list[WeakQuestionReview]],
        crop_region: tuple[float, float, float, float],
        learning_questions: Mapping[str, list[LearningQuestionReview]] | None = None,
    ):
        super().__init__()
        self.subject = subject
        self.report = report
        self.crop_region = crop_region
        self.card_stats = dict(card_stats)
        self.quick_review_dialog: QuickReviewDialog | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 20, 32, 24)
        layout.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(self.back_button())
        answer_note = (
            f"Không tìm thấy {report.csv_path}"
            if not report.file_found
            else f"{report.valid_count} câu có đáp án thi • {len(report.missing)} câu thiếu đáp án"
        )
        title, subtitle = page_title(
            subject.name, f"{subject.question_count} câu • {answer_note}"
        )
        heading = QVBoxLayout()
        heading.addWidget(title)
        heading.addWidget(subtitle)
        top.addLayout(heading, 1)
        layout.addLayout(top)
        self.progress_summary = QLabel()
        self.progress_summary.setObjectName("subjectProgressSummary")
        self._update_progress_summary()
        layout.addWidget(self.progress_summary)

        # Giữ một vùng có chiều cao bằng kích thước hover tối đa để animation
        # không làm QVBoxLayout đẩy header/dashboard ra khỏi cửa sổ.
        cards_container = QWidget()
        cards_container.setObjectName("studyModeCardsContainer")
        cards_container.setFixedHeight(StudyModeCard.HOVER_SIZE.height() + 20)
        cards_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        cards_layout = QHBoxLayout(cards_container)
        cards_layout.setContentsMargins(0, 10, 0, 10)
        cards_layout.setSpacing(18)
        cards_layout.addSpacerItem(
            QSpacerItem(20, 0, QSizePolicy.Expanding, QSizePolicy.Minimum)
        )
        choices = [
            (
                "flash",
                "🗂️",
                "Học bình thường",
                "Flash Cards — ghi nhớ từng câu theo nhịp của bạn",
            ),
            (
                "cram",
                "⚡",
                "Học cấp tốc",
                "Chinh phục queue 10 câu và ôn lại câu trả lời sai",
            ),
            (
                "exam",
                "📝",
                "Tạo bộ đề thi",
                "Trộn câu thích ứng, hẹn giờ và lưu kết quả",
            ),
        ]
        self.mode_cards: dict[str, StudyModeCard] = {}
        for key, icon, label, description in choices:
            card = StudyModeCard(key, icon, label, description)
            card.clicked.connect(self.mode_selected)
            card.hover_changed.connect(self._focus_mode_card)
            self.mode_cards[key] = card
            cards_layout.addWidget(card, alignment=Qt.AlignCenter)
        cards_layout.addSpacerItem(
            QSpacerItem(20, 0, QSizePolicy.Expanding, QSizePolicy.Minimum)
        )
        layout.addWidget(cards_container)

        self.dashboard_heading = QLabel(
            f"Thống kê môn {subject.name} & Ôn tập nhanh"
        )
        self.dashboard_heading.setObjectName("dashboardHeading")
        layout.addWidget(self.dashboard_heading)
        dashboard_note = QLabel(
            "Double-click hoặc nhấn Space để xem nhanh ảnh và đáp án đúng. "
            "Câu chưa thuộc theo thứ tự file; lỗi sai ưu tiên tỷ lệ cao nhất."
        )
        dashboard_note.setObjectName("subtitle")
        layout.addWidget(dashboard_note)

        self.statistics_tabs = QTabWidget()
        self.statistics_tabs.setObjectName("statisticsDashboard")
        self.statistics_tabs.tabBar().setObjectName("statisticsTypeTabs")

        self.learning_tabs = QTabWidget()
        self.learning_tabs.setObjectName("learningDashboard")
        self.dashboard_tabs = QTabWidget()
        self.dashboard_tabs.setObjectName("weaknessDashboard")
        self.learning_tables: dict[str, QTableWidget] = {}
        self.weak_tables: dict[str, QTableWidget] = {}
        self._learning_entries_by_table: dict[
            QTableWidget, list[LearningQuestionReview]
        ] = {}
        self._weak_entries_by_table: dict[
            QTableWidget, list[WeakQuestionReview]
        ] = {}
        self._quick_review_shortcuts: list[QShortcut] = []
        tab_labels = {
            "Fill_blanks": "Điền khuyết",
            "Selections_1_choose": "Chọn một",
            "Selections_Multiple_choose": "Chọn nhiều",
            "True_False": "Đúng/Sai",
        }
        learning_questions = learning_questions or {}
        for category in CATEGORIES:
            learning_table = self._build_learning_table(
                learning_questions.get(category, [])
            )
            self.learning_tables[category] = learning_table
            self.learning_tabs.addTab(learning_table, tab_labels[category])
            error_table = self._build_weakness_table(
                weak_questions.get(category, [])
            )
            self.weak_tables[category] = error_table
            self.dashboard_tabs.addTab(error_table, tab_labels[category])
        self.statistics_tabs.addTab(self.learning_tabs, "Câu chưa học")
        self.statistics_tabs.addTab(self.dashboard_tabs, "Lỗi sai")
        layout.addWidget(self.statistics_tabs, 1)

    def _update_progress_summary(self) -> None:
        self.progress_summary.setText(
            f"Flashcard: {self.card_stats.get('known', 0)} đã thuộc • "
            f"{self.card_stats.get('learning', 0)} chưa thuộc • "
            f"{self.card_stats.get('new', 0)} thẻ mới"
        )

    def _focus_mode_card(self, active_mode: str, focused: bool) -> None:
        for mode, card in self.mode_cards.items():
            card.set_dimmed(focused and mode != active_mode)

    def _build_weakness_table(
        self, entries: list[WeakQuestionReview]
    ) -> QTableWidget:
        entries = list(entries)
        table = QTableWidget(max(1, len(entries)), 3)
        self._weak_entries_by_table[table] = entries
        table.setObjectName("weakQuestionTable")
        table.setHorizontalHeaderLabels(
            ["Câu hỏi", "Số lần sai / Tổng", "Tỷ lệ sai"]
        )
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        if not entries:
            empty = QTableWidgetItem("Chưa ghi nhận câu trả lời sai trong nhóm này.")
            empty.setFlags(Qt.ItemIsEnabled)
            empty.setForeground(QColor("#8E8E93"))
            table.setItem(0, 0, empty)
            table.setSpan(0, 0, 1, 3)
        for row, review in enumerate(entries):
            name = Path(review.question.relative_path).name
            name_cell = QTableWidgetItem(name)
            name_cell.setData(Qt.UserRole, review)
            name_cell.setToolTip(review.question.relative_path)
            attempts_cell = QTableWidgetItem(
                f"{review.wrong_count} / {review.total_attempts}"
            )
            attempts_cell.setTextAlignment(Qt.AlignCenter)
            rate_cell = QTableWidgetItem(f"{review.error_rate * 100:.1f}%")
            rate_cell.setForeground(QColor("#FF453A"))
            rate_cell.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 0, name_cell)
            table.setItem(row, 1, attempts_cell)
            table.setItem(row, 2, rate_cell)
        table.cellDoubleClicked.connect(
            lambda row, _column, source=table: self._open_quick_review(source, row)
        )
        open_shortcut = QShortcut(QKeySequence(Qt.Key_Space), table)
        open_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        open_shortcut.activated.connect(
            lambda source=table: self._open_selected_quick_review(source)
        )
        self._quick_review_shortcuts.append(open_shortcut)
        return table

    def _build_learning_table(
        self, entries: list[LearningQuestionReview]
    ) -> QTableWidget:
        ordered_entries = list(entries)
        table = QTableWidget(max(1, len(ordered_entries)), 2)
        self._learning_entries_by_table[table] = ordered_entries
        table.setObjectName("learningQuestionTable")
        table.setHorizontalHeaderLabels(["Câu hỏi", "Trạng thái"])
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self._render_learning_table(table)
        table.cellDoubleClicked.connect(
            lambda row, _column, source=table: self._open_quick_review(source, row)
        )
        open_shortcut = QShortcut(QKeySequence(Qt.Key_Space), table)
        open_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        open_shortcut.activated.connect(
            lambda source=table: self._open_selected_quick_review(source)
        )
        self._quick_review_shortcuts.append(open_shortcut)
        return table

    def _render_learning_table(self, table: QTableWidget) -> None:
        entries = self._learning_entries_by_table[table]
        table.clearContents()
        table.clearSpans()
        table.setRowCount(max(1, len(entries)))
        if not entries:
            empty = QTableWidgetItem(
                "Không có câu nào ở trạng thái Chưa thuộc trong nhóm này."
            )
            empty.setFlags(Qt.ItemIsEnabled)
            empty.setForeground(QColor("#8E8E93"))
            table.setItem(0, 0, empty)
            table.setSpan(0, 0, 1, 2)
            return
        for row, review in enumerate(entries):
            name = Path(review.question.relative_path).name
            name_cell = QTableWidgetItem(name)
            name_cell.setData(Qt.UserRole, review)
            name_cell.setToolTip(review.question.relative_path)
            status_cell = QTableWidgetItem("Chưa thuộc")
            status_cell.setForeground(QColor("#FF453A"))
            status_cell.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 0, name_cell)
            table.setItem(row, 1, status_cell)

    def _open_selected_quick_review(self, table: QTableWidget) -> None:
        row = table.currentRow()
        if row >= 0:
            self._open_quick_review(table, row)

    def _open_quick_review(self, table: QTableWidget, row: int) -> None:
        is_learning_review = table in self._learning_entries_by_table
        entries = (
            self._learning_entries_by_table.get(table, [])
            if is_learning_review
            else self._weak_entries_by_table.get(table, [])
        )
        if not 0 <= row < len(entries):
            return
        if self.quick_review_dialog is not None:
            self.quick_review_dialog.close()
            self.quick_review_dialog.deleteLater()
        self.quick_review_dialog = QuickReviewDialog(
            entries,
            row,
            self.crop_region,
            allow_rating=is_learning_review,
            parent=self,
        )
        if is_learning_review:
            self.quick_review_dialog.rating_requested.connect(
                self._handle_learning_rating
            )
        self.quick_review_dialog.show()
        self.quick_review_dialog.raise_()
        self.quick_review_dialog.activateWindow()

    def _handle_learning_rating(self, question_id: str, known: bool) -> None:
        self.learning_status_changed.emit(question_id, known)
        for table, entries in self._learning_entries_by_table.items():
            matched_index = next(
                (
                    index
                    for index, entry in enumerate(entries)
                    if entry.question.id == question_id
                ),
                None,
            )
            if matched_index is None:
                continue
            review = entries[matched_index]
            previous_state = review.card_state
            if not known:
                if previous_state == "new":
                    entries[matched_index] = LearningQuestionReview(
                        question=review.question,
                        correct_answer=review.correct_answer,
                        card_state="learning",
                    )
                    self.card_stats["new"] = max(0, self.card_stats.get("new", 0) - 1)
                    self.card_stats["learning"] = self.card_stats.get("learning", 0) + 1
                    self._update_progress_summary()
                return
            del entries[matched_index]
            self._render_learning_table(table)
            self.card_stats[previous_state] = max(
                0, self.card_stats.get(previous_state, 0) - 1
            )
            self.card_stats["known"] = self.card_stats.get("known", 0) + 1
            self._update_progress_summary()
            return


@dataclass(slots=True)
class FlashHistoryEntry:
    question: Question
    known: bool


@dataclass(slots=True)
class CramHistoryEntry:
    question: Question
    selected_answer: str
    correct_answer: str
    is_correct: bool


class FlashcardScreen(BasePage):
    def __init__(
        self,
        service: FlashcardService,
        crop_region: tuple[float, float, float, float],
    ):
        super().__init__()
        self.service = service
        self.history_stack: list[FlashHistoryEntry] = []
        self._history_cursor: int | None = None
        self._live_state: FlashState | None = None
        self._completion_announced = False
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self.back_button())
        title, _ = page_title("Flash Cards")
        top.addWidget(title)
        top.addStretch()
        self.progress = QLabel()
        top.addWidget(self.progress)
        layout.addLayout(top)
        self.stats = QLabel()
        layout.addWidget(self.stats)
        self.session_progress = StudyProgressBar()
        self.session_progress.setAccessibleName("Tiến trình phiên Flashcard")
        layout.addWidget(self.session_progress)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        image_area = QWidget()
        image_layout = QVBoxLayout(image_area)
        image_layout.setContentsMargins(0, 0, 0, 0)
        self.history_notice = QLabel()
        self.history_notice.setObjectName("subtitle")
        self.history_notice.hide()
        image_layout.addWidget(self.history_notice)
        self.viewer = QuestionImageViewer()
        self.viewer.set_crop_region(crop_region)
        self.viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        image_layout.addWidget(self.viewer, 1)
        splitter.addWidget(image_area)

        self.answer_panel = QFrame()
        self.answer_panel.setObjectName("flashAnswerPanel")
        self.answer_panel.setMinimumWidth(260)
        self.answer_panel.setMaximumWidth(340)
        self.answer_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        answer_layout = QVBoxLayout(self.answer_panel)
        answer_layout.setContentsMargins(20, 20, 20, 16)
        self.answer_title = QLabel("Đáp án đúng")
        self.answer_title.setObjectName("flashAnswerTitle")
        self.answer_title.setAlignment(Qt.AlignCenter)
        self.answer_title.hide()
        self.answer_label = QLabel()
        self.answer_label.setObjectName("flashAnswerValue")
        self.answer_label.setAlignment(Qt.AlignCenter)
        self.answer_label.setWordWrap(True)
        self.answer_label.hide()
        answer_layout.addStretch(1)
        answer_layout.addWidget(self.answer_title)
        answer_layout.addWidget(self.answer_label)
        answer_layout.addStretch(1)
        hotkeys = QFrame()
        hotkeys.setObjectName("hotkeyHints")
        hotkey_layout = QVBoxLayout(hotkeys)
        hotkey_layout.setContentsMargins(12, 10, 12, 10)
        hotkey_title = QLabel("PHÍM TẮT")
        hotkey_title.setObjectName("hotkeyTitle")
        hotkey_text = QLabel("←  →  Chuyển câu\nSpace  Hiện / ẩn đáp án\nESC  Thoát")
        hotkey_text.setObjectName("hotkeyText")
        hotkey_text.setWordWrap(True)
        hotkey_layout.addWidget(hotkey_title)
        hotkey_layout.addWidget(hotkey_text)
        answer_layout.addWidget(hotkeys)
        splitter.addWidget(self.answer_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([920, 300])
        layout.addWidget(splitter, 1)

        controls = QHBoxLayout()
        self.new_button = secondary(QPushButton("Học lại"))
        self.learning_button = secondary(QPushButton("Chỉ học Chưa thuộc"))
        self.reveal_button = QPushButton("Hiện đáp án (Space)")
        self.unknown_button = QPushButton("Chưa thuộc")
        self.known_button = QPushButton("Đã thuộc")
        self.unknown_button.setProperty("danger", True)
        controls.addWidget(self.new_button)
        controls.addWidget(self.learning_button)
        controls.addStretch()
        controls.addWidget(self.reveal_button)
        controls.addWidget(self.unknown_button)
        controls.addWidget(self.known_button)
        layout.addLayout(controls)
        self.reveal_button.clicked.connect(self.viewer.toggle_answer)
        self.viewer.answer_revealed.connect(self._reveal_current_answer)
        self.viewer.answer_hidden.connect(self._hide_current_answer)
        self.known_button.clicked.connect(lambda: self._rate(True))
        self.unknown_button.clicked.connect(lambda: self._rate(False))
        self.new_button.clicked.connect(self._restart)
        self.learning_button.clicked.connect(lambda: self._new(True))
        self.shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        self.shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.shortcut.activated.connect(self.viewer.toggle_answer)
        self.left_shortcut = QShortcut(QKeySequence(Qt.Key_Left), self)
        self.left_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.left_shortcut.activated.connect(self._previous_question)
        self.right_shortcut = QShortcut(QKeySequence(Qt.Key_Right), self)
        self.right_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.right_shortcut.activated.connect(self._next_question)
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.escape_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.escape_shortcut.activated.connect(self.back_requested)
        self._render(self.service.resume_or_start())

    def _clear_answer_panel(self) -> None:
        self.answer_title.hide()
        self.answer_label.clear()
        self.answer_label.hide()

    def _show_answer(self, question: Question) -> None:
        answer = question.correct_answer
        self.answer_title.setText("Đáp án đúng" if answer else "Chưa có đáp án")
        self.answer_label.setText(answer or "—")
        self.answer_title.show()
        self.answer_label.show()

    def _reveal_current_answer(self) -> None:
        if self._history_cursor is not None:
            entry = self.history_stack[self._history_cursor]
            self._show_answer(entry.question)
            self.reveal_button.setText("Ẩn đáp án (Space)")
            return
        state = self.service.state()
        if state.question is not None:
            self._show_answer(state.question)
            self._enable_rating(True)
            self.reveal_button.setText("Ẩn đáp án (Space)")

    def _hide_current_answer(self) -> None:
        self._clear_answer_panel()
        self._enable_rating(False)
        self.reveal_button.setText("Hiện đáp án (Space)")

    def _restart(self) -> None:
        try:
            state = self.service.restart()
        except ValueError as exc:
            QMessageBox.information(self, "Không thể bắt đầu", str(exc))
            return
        self.history_stack.clear()
        self._history_cursor = None
        self._completion_announced = False
        self._render(state)

    def _new(self, learning: bool) -> None:
        try:
            state = self.service.start_new(learning)
        except ValueError as exc:
            QMessageBox.information(self, "Không thể bắt đầu", str(exc))
            return
        self.history_stack.clear()
        self._history_cursor = None
        self._completion_announced = False
        self._render(state)

    def _rate(self, known: bool) -> None:
        if self._history_cursor is not None or not self.viewer.answer_visible:
            return
        state = self.service.state()
        if state.question is not None:
            self.history_stack.append(FlashHistoryEntry(state.question, known))
        self._render(self.service.rate_current(known))

    def _previous_question(self) -> None:
        if not self.history_stack:
            return
        if self._history_cursor is None:
            self._history_cursor = len(self.history_stack) - 1
        elif self._history_cursor > 0:
            self._history_cursor -= 1
        self._show_history()

    def _next_question(self) -> None:
        if self._history_cursor is not None:
            if self._history_cursor < len(self.history_stack) - 1:
                self._history_cursor += 1
                self._show_history()
            else:
                self._history_cursor = None
                if self._live_state is not None:
                    self._render(self._live_state)
            return
        state = self.service.state()
        if state.completed or state.question is None:
            return
        # Right arrow is an explicit skip and therefore counts as Chưa thuộc.
        self.history_stack.append(FlashHistoryEntry(state.question, False))
        self._render(self.service.rate_current(False))

    def _show_history(self) -> None:
        if self._history_cursor is None:
            return
        entry = self.history_stack[self._history_cursor]
        self.viewer.load_image(
            entry.question.absolute_path,
            reveal=True,
            category=entry.question.category,
        )
        self._show_answer(entry.question)
        self.reveal_button.setText("Ẩn đáp án (Space)")
        self.progress.setText(
            f"Xem lại {self._history_cursor + 1}/{len(self.history_stack)}"
        )
        result = "Đã thuộc" if entry.known else "Chưa thuộc"
        self.history_notice.setText(
            f"Chỉ xem — Câu này đã được đánh dấu: {result}. Dùng ←/→ để điều hướng."
        )
        self.history_notice.show()
        self._enable_rating(False)
        self.reveal_button.setEnabled(False)
        self.new_button.setEnabled(False)
        self.learning_button.setEnabled(False)

    def _enable_rating(self, enabled: bool) -> None:
        self.known_button.setEnabled(enabled)
        self.unknown_button.setEnabled(enabled)

    def _render(self, state: FlashState) -> None:
        self._live_state = state
        self._history_cursor = None
        self.history_notice.hide()
        self._clear_answer_panel()
        self.reveal_button.setText("Hiện đáp án (Space)")
        self.new_button.setEnabled(True)
        self.learning_button.setEnabled(True)
        card_stats = self.service.stats()
        self.stats.setText(
            f"Đã thuộc: {card_stats['known']}  •  Chưa thuộc: {card_stats['learning']}  •  "
            f"Mới: {card_stats['new']}"
        )
        self.session_progress.setRange(0, max(1, state.total))
        self.session_progress.setValue(min(state.position, state.total))
        self.session_progress.setToolTip(
            f"Đã tương tác {min(state.position, state.total)}/{state.total} câu"
        )
        if state.completed or state.question is None:
            self.progress.setText(f"Hoàn thành {state.total}/{state.total}")
            self._enable_rating(False)
            self.reveal_button.setEnabled(False)
            if not self._completion_announced:
                self._completion_announced = True
                QMessageBox.information(
                    self, "Hoàn thành", "Bạn đã hoàn thành phiên Flashcard!"
                )
                self._restart()
            return
        self.progress.setText(f"Câu {state.position + 1}/{state.total}")
        try:
            self.viewer.load_image(
                state.question.absolute_path, category=state.question.category
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Lỗi ảnh", str(exc))
        self.reveal_button.setEnabled(True)
        self._enable_rating(False)


class CrammingScreen(BasePage):
    def __init__(
        self, service: CrammingService, crop_region: tuple[float, float, float, float]
    ):
        super().__init__()
        self.service = service
        self.history_stack: list[CramHistoryEntry] = []
        self._history_cursor: int | None = None
        self._live_state: CramState | None = None
        self._pending_state: CramState | None = None
        self._awaiting_navigation = False
        self._live_selection = ""
        self._completion_announced = False
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self.back_button())
        title, _ = page_title("Học cấp tốc")
        top.addWidget(title)
        top.addSpacerItem(
            QSpacerItem(20, 0, QSizePolicy.Expanding, QSizePolicy.Minimum)
        )
        self.progress = QLabel()
        top.addWidget(self.progress)
        layout.addLayout(top)
        self.round_progress = SegmentedProgressBar()
        self.round_progress.setAccessibleName("Tiến trình các vòng Cramming")
        layout.addWidget(self.round_progress)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.history_notice = QLabel()
        self.history_notice.setObjectName("subtitle")
        self.history_notice.hide()
        left_layout.addWidget(self.history_notice)
        self.viewer = QuestionImageViewer()
        self.viewer.set_crop_region(crop_region)
        self.viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.viewer, 1)
        self.feedback = QLabel("Chọn đáp án rồi nhấn Enter để kiểm tra.")
        self.feedback.setWordWrap(True)
        left_layout.addWidget(self.feedback)
        splitter.addWidget(left)

        self.sidebar = AssessmentSidebar()
        self.answer_options = self.sidebar.answer_options
        self.options_box = self.sidebar.answer_group
        self.navigator = self.sidebar.navigation
        self.new_cycle = secondary(QPushButton("Bắt đầu chu kỳ mới"))
        self.confirm_answer = QPushButton("Xác nhận đáp án (Enter)")
        self.previous = secondary(QPushButton("← Câu trước"))
        self.next = secondary(QPushButton("Câu tiếp →"))
        self.sidebar.add_action(self.confirm_answer)
        self.sidebar.add_action_row(self.previous, self.next)
        self.sidebar.add_action(self.new_cycle)
        splitter.addWidget(self.sidebar)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([920, 300])
        layout.addWidget(splitter, 1)

        self.new_cycle.clicked.connect(self._start_new)
        self.confirm_answer.clicked.connect(self._submit_answer)
        self.previous.clicked.connect(self._previous_question)
        self.next.clicked.connect(self._next_question)
        self.navigator.question_selected.connect(self._go_to_round_item)
        self._assessment_shortcuts = install_assessment_keymap(
            self,
            self.answer_options.toggle_option,
            self._submit_answer,
            self._previous_question,
            self._next_question,
        )
        self._render(self.service.resume_or_start())

    def keyPressEvent(self, event) -> None:
        option = OPTION_KEY_MAP.get(event.key())
        if option is not None:
            self.answer_options.toggle_option(option)
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._submit_answer()
            event.accept()
            return
        if event.key() == Qt.Key_Left:
            self._previous_question()
            event.accept()
            return
        if event.key() == Qt.Key_Right:
            self._next_question()
            event.accept()
            return
        super().keyPressEvent(event)

    def _start_new(self) -> None:
        answer = QMessageBox.question(
            self,
            "Chu kỳ mới",
            "Chu kỳ đang học (nếu có) sẽ được kết thúc. Tiếp tục?",
        )
        if answer == QMessageBox.Yes:
            self.history_stack.clear()
            self._history_cursor = None
            self._pending_state = None
            self._awaiting_navigation = False
            self._live_selection = ""
            self._completion_announced = False
            self._render(self.service.start_new())

    def _submit_answer(self) -> None:
        if self._awaiting_navigation or self._history_cursor is not None:
            return
        state = self._live_state or self.service.state()
        if state.completed or state.question is None:
            return
        selected = self.answer_options.selected_answer()
        if not selected:
            self.feedback.setText("Hãy chọn ít nhất một đáp án trước khi nhấn Enter.")
            self.feedback.setStyleSheet("color: #FF9F0A; font-weight: 600")
            return
        self._grade_current(state, selected)

    def _grade_current(self, state: CramState, selected: str) -> None:
        if state.question is None:
            return
        correct_answer = state.question.correct_answer
        is_correct = self.service.is_answer_correct(state.question, selected)
        self.history_stack.append(
            CramHistoryEntry(
                question=state.question,
                selected_answer=selected,
                correct_answer=correct_answer,
                is_correct=is_correct,
            )
        )
        self.answer_options.show_feedback(state.question, selected, correct_answer)
        self._set_navigation_question_state(
            state.question.id, "correct" if is_correct else "wrong"
        )
        self.viewer.reveal_answer()
        self.confirm_answer.setEnabled(False)
        self._awaiting_navigation = True
        self._pending_state = self.service.rate_current(is_correct)
        self._live_selection = ""
        if is_correct:
            self.feedback.setText(
                "Chính xác — câu hỏi được loại khỏi hàng đợi. "
                "Nhấn → để sang câu tiếp theo hoặc ← để xem câu trước."
            )
            self.feedback.setStyleSheet("color: #30D158; font-weight: 700")
        elif selected:
            self.feedback.setText(
                f"Chưa đúng — đáp án đúng: {correct_answer}. Câu hỏi đã được đưa "
                "xuống cuối hàng đợi. Nhấn → để tiếp tục hoặc ← để xem câu trước."
            )
            self.feedback.setStyleSheet("color: #FF453A; font-weight: 700")
        self.previous.setEnabled(len(self.history_stack) > 1)
        self.next.setEnabled(True)

    def _previous_question(self) -> None:
        if not self.history_stack:
            return
        if self._history_cursor == -1:
            self._history_cursor = len(self.history_stack) - 1
            self._show_history()
            return
        if self._history_cursor is None:
            if self._awaiting_navigation:
                if len(self.history_stack) < 2:
                    self.feedback.setText("Chưa có câu nào trước câu hiện tại.")
                    self.feedback.setStyleSheet("color: #FF9F0A; font-weight: 600")
                    return
                self._history_cursor = len(self.history_stack) - 2
            else:
                self._live_selection = self.answer_options.selected_answer()
                self._history_cursor = len(self.history_stack) - 1
        elif self._history_cursor > 0:
            self._history_cursor -= 1
        self._show_history()

    def _next_question(self) -> None:
        if self._history_cursor == -1:
            self._history_cursor = None
            if self._live_state is not None:
                self._render(self._live_state)
            return
        if self._history_cursor is not None:
            if self._history_cursor < len(self.history_stack) - 1:
                self._history_cursor += 1
                self._show_history()
            else:
                self._history_cursor = None
                if self._awaiting_navigation:
                    self._advance_after_grade()
                elif self._live_state is not None:
                    self._render(self._live_state, preserve_selection=True)
            return
        if self._awaiting_navigation:
            self._advance_after_grade()
            return
        self.feedback.setText("Hãy nhấn Enter để kiểm tra đáp án trước khi chuyển câu.")
        self.feedback.setStyleSheet("color: #FF9F0A; font-weight: 600")

    def _advance_after_grade(self) -> None:
        state = self._pending_state or self.service.state()
        self._pending_state = None
        self._awaiting_navigation = False
        self._render(state)

    def _show_history(self) -> None:
        if self._history_cursor is None:
            return
        entry = self.history_stack[self._history_cursor]
        self.viewer.load_image(
            entry.question.absolute_path,
            reveal=True,
            category=entry.question.category,
        )
        self.answer_options.show_feedback(
            entry.question, entry.selected_answer, entry.correct_answer
        )
        verdict = "Đúng" if entry.is_correct else "Sai"
        self.history_notice.setText(
            f"Chỉ xem {self._history_cursor + 1}/{len(self.history_stack)} — "
            f"Bạn chọn: {entry.selected_answer or 'Không chọn'} • "
            f"Đáp án đúng: {entry.correct_answer} • {verdict}"
        )
        self.history_notice.show()
        self.feedback.setText("Chế độ chỉ xem — dùng ←/→ để điều hướng lịch sử.")
        self.feedback.setStyleSheet("color: #8E8E93")
        self.confirm_answer.setEnabled(False)
        self.new_cycle.setEnabled(False)
        self.previous.setEnabled(self._history_cursor > 0)
        self.next.setEnabled(True)
        self._select_navigation_question(entry.question.id)

    def _show_mastered_question(self, index: int) -> None:
        items = self.service.current_round_items()
        if not 0 <= index < len(items):
            return
        target = items[index]
        for history_index in range(len(self.history_stack) - 1, -1, -1):
            if self.history_stack[history_index].question.id == target.question.id:
                self._history_cursor = history_index
                self._show_history()
                return
        self._history_cursor = -1
        self.viewer.load_image(
            target.question.absolute_path,
            reveal=True,
            category=target.question.category,
        )
        self.answer_options.show_feedback(
            target.question, "", target.question.correct_answer
        )
        self.history_notice.setText(
            f"Chỉ xem — Câu {index + 1} của vòng đã hoàn thành. "
            f"Đáp án đúng: {target.question.correct_answer}"
        )
        self.history_notice.show()
        self.feedback.setText("Chế độ chỉ xem — chọn một ô chưa hoàn thành để tiếp tục.")
        self.feedback.setStyleSheet("color: #8E8E93")
        self.confirm_answer.setEnabled(False)
        self.new_cycle.setEnabled(False)
        self.navigator.set_current(index)

    def _go_to_round_item(self, index: int) -> None:
        if self._awaiting_navigation:
            self.feedback.setText(
                "Kết quả đang hiển thị — dùng → để tiếp tục hoặc ← để xem câu trước."
            )
            self.feedback.setStyleSheet("color: #FF9F0A; font-weight: 600")
            return
        items = self.service.current_round_items()
        if not 0 <= index < len(items):
            return
        target = items[index]
        if target.mastered:
            self._show_mastered_question(index)
            return
        state = self.service.state()
        if state.question is not None and state.question.id == target.question.id:
            self._history_cursor = None
            self._render(state, preserve_selection=True)
            return
        self._live_selection = ""
        self._render(self.service.focus_question(target.question.id))

    def _select_navigation_question(self, question_id: str) -> None:
        for index, item in enumerate(self.service.current_round_items()):
            if item.question.id == question_id:
                self.navigator.set_current(index)
                return
        self.navigator.set_current(-1)

    def _set_navigation_question_state(self, question_id: str, nav_state: str) -> None:
        for index, item in enumerate(self.service.current_round_items()):
            if item.question.id == question_id:
                self.navigator.set_state(index, nav_state)
                self.navigator.set_current(index)
                return

    def _update_navigation(self, state: CramState) -> None:
        items = self.service.current_round_items()
        self.navigator.set_count(len(items))
        for index, item in enumerate(items):
            nav_state = (
                "correct"
                if item.mastered
                else ("wrong" if item.wrong_count else "unanswered")
            )
            self.navigator.set_state(index, nav_state)
        self.navigator.set_progress(state.round_mastered, state.round_total)
        if state.question is not None:
            self._select_navigation_question(state.question.id)
        else:
            self.navigator.set_current(-1)

    def _render(self, state: CramState, preserve_selection: bool = False) -> None:
        self._pending_state = None
        self._awaiting_navigation = False
        self._live_state = state
        self._history_cursor = None
        self.history_notice.hide()
        self.new_cycle.setEnabled(True)
        self.round_progress.set_progress(
            total_rounds=state.total_rounds,
            current_round=state.current_round,
            round_mastered=state.round_mastered,
            round_total=state.round_total,
            completed=state.completed,
        )
        self._update_navigation(state)
        if state.completed or state.question is None:
            self.progress.setText("Chu kỳ đã hoàn thành")
            self.options_box.setEnabled(False)
            self.confirm_answer.setEnabled(False)
            self.feedback.setText("Chu kỳ đã hoàn thành.")
            self.feedback.setStyleSheet("color: #30D158; font-weight: 700")
            self.previous.setEnabled(bool(self.history_stack))
            self.next.setEnabled(False)
            if not self._completion_announced:
                self._completion_announced = True
                QMessageBox.information(
                    self,
                    "Chúc mừng!",
                    "Bạn đã làm đúng toàn bộ câu hỏi trong chu kỳ. "
                    "Hãy bắt đầu chu kỳ mới khi sẵn sàng.",
                )
            return
        self.options_box.setEnabled(True)
        self.progress.setText(
            f"Chu kỳ #{state.cycle_id}  •  Vòng {state.current_round}/{state.total_rounds}  •  "
            f"Còn {state.remaining} câu  •  Đã đúng: {state.mastered}  •  Lượt sai: {state.wrong}"
        )
        self.viewer.load_image(
            state.question.absolute_path, category=state.question.category
        )
        if not preserve_selection:
            self._live_selection = ""
        self.answer_options.set_question(
            state.question, selected_answer=self._live_selection
        )
        self.feedback.setText(
            "Chọn đáp án rồi nhấn Enter để kiểm tra; sau đó dùng ←/→ để điều hướng."
        )
        self.feedback.setStyleSheet("")
        self.confirm_answer.setEnabled(True)
        self.previous.setEnabled(bool(self.history_stack))
        self.next.setEnabled(True)


class ExamConfigScreen(BasePage):
    exam_requested = pyqtSignal(object)

    def __init__(self, subject: Subject, exam_service: ExamService, report: AnswerKeyReport):
        super().__init__()
        self.subject = subject
        self.exam_service = exam_service
        self.max_available = 0
        self._updating_count = False
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self.back_button())
        answer_summary = (
            f"Không tìm thấy file đáp án tại {report.csv_path}. Hãy chạy công cụ OCR hoặc tạo file này."
            if not report.file_found
            else f"{report.valid_count} câu có đáp án hợp lệ; "
            f"{len(report.missing)} câu chưa thể đưa vào đề."
        )
        title, subtitle = page_title("Cấu hình bộ đề", answer_summary)
        heading = QVBoxLayout()
        heading.addWidget(title)
        heading.addWidget(subtitle)
        top.addLayout(heading, 1)
        layout.addLayout(top)
        form_card = QFrame()
        form_card.setObjectName("card")
        form = QFormLayout(form_card)
        categories_widget = QWidget()
        categories_layout = QVBoxLayout(categories_widget)
        categories_layout.setContentsMargins(0, 0, 0, 0)
        self.category_boxes: dict[str, QCheckBox] = {}
        for category in CATEGORIES:
            available = len(exam_service.eligible_questions([category]))
            box = QCheckBox(f"{CATEGORY_LABELS[category]} ({available} câu đủ đáp án)")
            box.setChecked(available > 0)
            box.setEnabled(available > 0)
            self.category_boxes[category] = box
            categories_layout.addWidget(box)
        form.addRow("Loại câu hỏi", categories_widget)
        self.count_combo = QComboBox()
        self.count_combo.addItems(["30", "40", "50", "Khác"])
        self.count_custom = QSpinBox()
        self.count_custom.setRange(1, 100000)
        self.count_custom.setValue(10)
        count_widget = QWidget()
        count_layout = QHBoxLayout(count_widget)
        count_layout.setContentsMargins(0, 0, 0, 0)
        count_layout.addWidget(self.count_combo)
        count_layout.addWidget(self.count_custom)
        self.count_custom.hide()
        form.addRow("Số câu hỏi", count_widget)
        self.time_combo = QComboBox()
        self.time_combo.addItems(["30", "40", "50", "60", "Khác"])
        self.time_custom = QSpinBox()
        self.time_custom.setRange(1, 10080)
        self.time_custom.setValue(30)
        time_widget = QWidget()
        time_layout = QHBoxLayout(time_widget)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.addWidget(self.time_combo)
        time_layout.addWidget(self.time_custom)
        self.time_custom.hide()
        form.addRow("Thời gian (phút)", time_widget)
        feedback_widget = QWidget()
        feedback_layout = QVBoxLayout(feedback_widget)
        feedback_layout.setContentsMargins(0, 0, 0, 0)
        self.immediate = QRadioButton("Hiện đáp án ngay sau khi xác nhận từng câu")
        self.deferred = QRadioButton("Chỉ hiện đáp án sau khi nộp bài")
        self.deferred.setChecked(True)
        feedback_layout.addWidget(self.immediate)
        feedback_layout.addWidget(self.deferred)
        form.addRow("Hiển thị đáp án", feedback_widget)
        layout.addWidget(form_card)
        self.pool_label = QLabel()
        layout.addWidget(self.pool_label)
        self.count_warning = QLabel()
        self.count_warning.setStyleSheet("color: #FF9F0A; font-weight: 600")
        self.count_warning.hide()
        layout.addWidget(self.count_warning)
        self._count_warning_timer = QTimer(self)
        self._count_warning_timer.setSingleShot(True)
        self._count_warning_timer.setInterval(3000)
        self._count_warning_timer.timeout.connect(self.count_warning.hide)
        layout.addStretch()
        self.start_button = QPushButton("Bắt đầu làm bài")
        self.start_button.clicked.connect(self._start)
        layout.addWidget(self.start_button, alignment=Qt.AlignRight)
        self.count_combo.currentTextChanged.connect(self._count_mode_changed)
        self.count_custom.lineEdit().textEdited.connect(
            self._custom_count_text_edited
        )
        self.time_combo.currentTextChanged.connect(
            lambda text: self.time_custom.setVisible(text == "Khác")
        )
        for box in self.category_boxes.values():
            box.toggled.connect(self._update_pool)
        self._update_pool()

    def _selected_categories(self) -> tuple[str, ...]:
        return tuple(key for key, box in self.category_boxes.items() if box.isChecked())

    def _selected_question_count(self) -> int:
        if self.count_combo.currentText() == "Khác":
            return self.count_custom.value()
        return int(self.count_combo.currentText())

    def _show_count_warning(self, message: str) -> None:
        self.count_warning.setText(message)
        self.count_warning.show()
        self._count_warning_timer.start()

    def _adjust_count_to_pool(self, requested: int) -> None:
        self._updating_count = True
        self.count_combo.setCurrentText("Khác")
        self.count_custom.setVisible(True)
        self.count_custom.setValue(self.max_available)
        self._updating_count = False
        if self.max_available > 0:
            self._show_count_warning(
                f"Đã điều chỉnh số câu từ {requested} xuống {self.max_available} "
                "theo các loại đang chọn."
            )
        else:
            self._show_count_warning(
                "Không có câu đủ điều kiện trong các loại đang chọn."
            )

    def _count_mode_changed(self, text: str) -> None:
        self.count_custom.setVisible(text == "Khác")
        if self._updating_count:
            return
        requested = self._selected_question_count()
        if requested > self.max_available:
            self._adjust_count_to_pool(requested)

    def _custom_count_text_edited(self, text: str) -> None:
        digits = "".join(char for char in text if char.isdigit())
        if not digits:
            return
        requested = int(digits)
        if requested > self.max_available:
            self.count_custom.setValue(self.max_available)
            self._show_count_warning(
                f"Tối đa {self.max_available} câu với các loại đang chọn; "
                "giá trị đã được giới hạn."
            )

    def _update_pool(self, _checked: bool | None = None) -> None:
        requested = self._selected_question_count()
        self.max_available = len(
            self.exam_service.eligible_questions(self._selected_categories())
        )
        if self.max_available > 0:
            self.count_custom.setRange(1, self.max_available)
        else:
            self.count_custom.setRange(0, 0)
        if requested > self.max_available:
            self._adjust_count_to_pool(requested)
        self.pool_label.setText(
            f"Có thể tạo đề từ {self.max_available} câu đủ điều kiện."
        )
        self.start_button.setEnabled(self.max_available > 0)

    def _start(self) -> None:
        categories = self._selected_categories()
        count = self._selected_question_count()
        duration = (
            self.time_custom.value()
            if self.time_combo.currentText() == "Khác"
            else int(self.time_combo.currentText())
        )
        config = ExamConfig(
            subject=self.subject.name,
            categories=categories,
            question_count=count,
            duration_minutes=duration,
            feedback_mode=(
                FeedbackMode.IMMEDIATE if self.immediate.isChecked() else FeedbackMode.DEFERRED
            ),
        )
        try:
            session = self.exam_service.create_session(config)
        except ValueError as exc:
            QMessageBox.warning(self, "Cấu hình chưa hợp lệ", str(exc))
            return
        self.exam_requested.emit(session)


class ExamScreen(BasePage):
    result_ready = pyqtSignal(object)

    def __init__(
        self,
        session: ExamSession,
        crop_region: tuple[float, float, float, float],
    ):
        super().__init__()
        self.session = session
        self._crop_region = crop_region
        self._switching = False
        self._end_monotonic = time.monotonic() + session.config.duration_minutes * 60
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(250)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self.back_button())
        title, _ = page_title("Mock Exam")
        top.addWidget(title)
        top.addStretch()
        self.position_label = QLabel()
        self.timer_label = QLabel()
        self.timer_label.setStyleSheet("font-size: 18px; font-weight: 700")
        top.addWidget(self.position_label)
        top.addSpacing(20)
        top.addWidget(self.timer_label)
        layout.addLayout(top)
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.viewer = QuestionImageViewer()
        self.viewer.set_crop_region(crop_region)
        self.viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.viewer, 1)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        left_layout.addWidget(self.feedback)
        splitter.addWidget(left)

        self.sidebar = AssessmentSidebar()
        self.answer_options = self.sidebar.answer_options
        self.options_box = self.sidebar.answer_group
        self.navigator = self.sidebar.navigation
        self.previous = secondary(QPushButton("← Câu trước"))
        self.confirm = QPushButton("Xác nhận đáp án")
        self.next = secondary(QPushButton("Câu sau →"))
        self.submit = QPushButton("Nộp bài")
        self.submit.setProperty("danger", True)
        self.sidebar.add_action(self.confirm)
        self.sidebar.add_action_row(self.previous, self.next)
        self.sidebar.add_action(self.submit)
        self.navigator.set_count(len(session.items))
        self.navigator.question_selected.connect(self.go_to)
        splitter.addWidget(self.sidebar)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([920, 300])
        layout.addWidget(splitter, 1)
        self._option_widgets = []
        self.previous.clicked.connect(lambda: self.go_to(self.session.current_index - 1))
        self.next.clicked.connect(lambda: self.go_to(self.session.current_index + 1))
        self.confirm.clicked.connect(self._confirm_current)
        self.submit.clicked.connect(lambda: self._request_submit(False))
        self.answer_options.selection_changed.connect(self._answer_selection_changed)
        self._assessment_shortcuts = install_assessment_keymap(
            self,
            self.answer_options.toggle_option,
            self._enter_action,
            lambda: self.go_to(self.session.current_index - 1),
            lambda: self.go_to(self.session.current_index + 1),
        )
        self._render_current()
        self._tick()

    def keyPressEvent(self, event) -> None:
        option = OPTION_KEY_MAP.get(event.key())
        if option is not None:
            self.answer_options.toggle_option(option)
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._enter_action()
            event.accept()
            return
        if event.key() == Qt.Key_Left:
            self.go_to(self.session.current_index - 1)
            event.accept()
            return
        if event.key() == Qt.Key_Right:
            self.go_to(self.session.current_index + 1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _enter_action(self) -> None:
        if self.session.config.feedback_mode == FeedbackMode.IMMEDIATE:
            self._confirm_current()
        else:
            self._request_submit(False)

    @property
    def active(self) -> bool:
        return not self.session.submitted

    def pause_countdown(self) -> None:
        self._timer.stop()

    def resume_countdown(self) -> None:
        if self.active:
            self._timer.start(250)
            self._tick()

    def discard_exam(self) -> None:
        """Dừng UI bài thi; ExamSession chưa submit nên không ghi SQLite."""
        self._timer.stop()

    def _build_options(self) -> None:
        item = self.session.current
        if (
            item.confirmed
            and self.session.config.feedback_mode == FeedbackMode.IMMEDIATE
        ):
            self.answer_options.show_feedback(
                item.question, item.selected_answer, item.question.correct_answer
            )
        else:
            self.answer_options.set_question(
                item.question,
                selected_answer=item.selected_answer,
                read_only=item.confirmed,
            )
        self._option_widgets = self.answer_options.option_widgets

    def _capture_answer(self) -> None:
        if not self._option_widgets or self.session.current.confirmed:
            return
        self.session.set_answer(self.answer_options.selected_answer())
        self._update_nav_item(self.session.current_index)

    def _answer_selection_changed(self, answer: str) -> None:
        if self.session.current.confirmed:
            return
        self.session.set_answer(answer)
        self._update_nav_item(self.session.current_index)

    def _update_nav_item(self, index: int) -> None:
        item = self.session.items[index]
        if (
            self.session.config.feedback_mode == FeedbackMode.IMMEDIATE
            and item.confirmed
        ):
            state = "correct" if item.is_correct else "wrong"
        else:
            state = "answered" if item.selected_answer else "unanswered"
        self.navigator.set_state(index, state)
        answered = sum(bool(question.selected_answer) for question in self.session.items)
        self.navigator.set_progress(answered, len(self.session.items))

    def _render_current(self) -> None:
        item = self.session.current
        reveal = item.confirmed and self.session.config.feedback_mode == FeedbackMode.IMMEDIATE
        self.viewer.load_image(
            item.question.absolute_path,
            reveal=reveal,
            category=item.question.category,
        )
        self._build_options()
        self.position_label.setText(
            f"Câu {self.session.current_index + 1}/{len(self.session.items)}"
        )
        can_navigate = (
            self.session.config.feedback_mode == FeedbackMode.DEFERRED or item.confirmed
        )
        self.previous.setEnabled(self.session.current_index > 0 and can_navigate)
        self.next.setEnabled(
            self.session.current_index < len(self.session.items) - 1 and can_navigate
        )
        self.confirm.setVisible(self.session.config.feedback_mode == FeedbackMode.IMMEDIATE)
        self.confirm.setEnabled(not item.confirmed)
        if reveal:
            question_value = 10.0 / len(self.session.items)
            awarded = item.calculate_score(question_value)
            verdict = "Đúng" if item.is_correct else ("Đúng một phần" if awarded > 0 else "Sai")
            self.feedback.setText(
                f"{verdict}. Điểm: {awarded:.2f}/{question_value:.2f}. "
                f"Đáp án đúng: {item.question.correct_answer}"
            )
        else:
            self.feedback.clear()
        self._switching = True
        self.navigator.set_current(self.session.current_index)
        self._switching = False

    def go_to(self, index: int) -> None:
        if not 0 <= index < len(self.session.items):
            return
        if (
            index != self.session.current_index
            and self.session.config.feedback_mode == FeedbackMode.IMMEDIATE
            and not self.session.current.confirmed
        ):
            QMessageBox.information(
                self,
                "Chưa xác nhận",
                "Hãy chọn và xác nhận đáp án hiện tại trước khi chuyển câu.",
            )
            self.navigator.set_current(self.session.current_index)
            return
        self._capture_answer()
        self.session.current_index = index
        self._render_current()

    def _confirm_current(self) -> None:
        self._capture_answer()
        try:
            self.session.confirm_current()
        except ValueError as exc:
            QMessageBox.information(self, "Chưa chọn đáp án", str(exc))
            return
        self._update_nav_item(self.session.current_index)
        self._render_current()

    def _tick(self) -> None:
        remaining = max(0, int(self._end_monotonic - time.monotonic() + 0.999))
        hours, remainder = divmod(remaining, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.timer_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        if remaining <= 0 and not self.session.submitted:
            self._submit("timeout")

    def _request_submit(self, auto: bool) -> None:
        if self.session.submitted:
            return
        self._capture_answer()
        if not auto:
            unanswered = sum(not item.selected_answer for item in self.session.items)
            response = QMessageBox.question(
                self,
                "Nộp bài",
                f"Bạn còn {unanswered} câu chưa trả lời. Nộp bài ngay?",
            )
            if response != QMessageBox.Yes:
                return
        self._submit("user")

    def _submit(self, reason: str) -> None:
        self.submit_exam(reason)

    def submit_exam(
        self, reason: str = "user", *, emit_result: bool = True
    ) -> ExamResult | None:
        if self.session.submitted:
            return None
        self._capture_answer()
        self._timer.stop()
        result = self.session.submit(reason)
        if emit_result:
            self.result_ready.emit(result)
        return result


class ResultScreen(BasePage):
    home_requested = pyqtSignal()
    retest_requested = pyqtSignal(str)

    def __init__(
        self, result: ExamResult, crop_region: tuple[float, float, float, float]
    ):
        super().__init__()
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        title, subtitle = page_title(
            "Kết quả bài thi",
            f"Đúng {result.correct}/{result.total} • Chưa trả lời {result.unanswered} • "
            f"Điểm {result.score:.2f}/10 ({result.score_percent:.2f}%)",
        )
        heading = QVBoxLayout()
        heading.addWidget(title)
        heading.addWidget(subtitle)
        top.addLayout(heading, 1)
        self.retest_button = secondary(QPushButton("↻ RE-Test"))
        self.retest_button.setToolTip("Làm một bài thi mới")
        self.retest_menu = QMenu(self.retest_button)
        self.retest_same_action = self.retest_menu.addAction(
            "Làm lại với cấu hình cũ"
        )
        self.retest_new_action = self.retest_menu.addAction(
            "Tự chọn lại option mới"
        )
        self.retest_same_action.triggered.connect(
            lambda: self.retest_requested.emit("same_config")
        )
        self.retest_new_action.triggered.connect(
            lambda: self.retest_requested.emit("new_config")
        )
        self.retest_button.setMenu(self.retest_menu)
        top.addWidget(self.retest_button)
        self.home_button = QPushButton("Về trang chủ")
        self.home_button.clicked.connect(self.home_requested)
        top.addWidget(self.home_button)
        layout.addLayout(top)
        splitter = QSplitter()
        self.table = QTableWidget(len(result.items) + 1, 3)
        self.table.setObjectName("resultTable")
        self.table.setHorizontalHeaderLabels(["NO", "Correct answer", "Điểm"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        for row, item in enumerate(result.items):
            number_cell = QTableWidgetItem(f"Câu {row + 1}")
            answer_cell = QTableWidgetItem(item.question.correct_answer)
            points_cell = QTableWidgetItem(self._format_points(item.awarded_score))
            answer_cell.setForeground(
                QColor("#30D158" if item.is_correct else "#FF453A")
            )
            answer_cell.setTextAlignment(Qt.AlignCenter)
            points_cell.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, number_cell)
            self.table.setItem(row, 1, answer_cell)
            self.table.setItem(row, 2, points_cell)

        total_row = len(result.items)
        total_cells = [
            QTableWidgetItem("Total"),
            QTableWidgetItem(result.status),
            QTableWidgetItem(f"{result.score:.2f} / 10"),
        ]
        status_color = QColor("#30D158" if result.passed else "#FF453A")
        total_cells[1].setForeground(status_color)
        total_cells[2].setForeground(status_color)
        for column, cell in enumerate(total_cells):
            font = cell.font()
            font.setBold(True)
            cell.setFont(font)
            cell.setBackground(QColor(10, 132, 255, 28))
            if column > 0:
                cell.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(total_row, column, cell)
        self.table.setRowHeight(total_row, 42)
        splitter.addWidget(self.table)
        self.viewer = QuestionImageViewer()
        self.viewer.set_crop_region(crop_region)
        splitter.addWidget(self.viewer)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([460, 760])
        layout.addWidget(splitter, 1)
        self._result = result
        self.table.currentCellChanged.connect(
            lambda row, _column, _previous_row, _previous_column: self._show_item(row)
        )
        if result.items:
            self.table.setCurrentCell(0, 0)

    @staticmethod
    def _format_points(value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".") or "0"

    def _show_item(self, index: int) -> None:
        if 0 <= index < len(self._result.items):
            self.viewer.load_image(
                self._result.items[index].question.absolute_path,
                reveal=True,
                category=self._result.items[index].question.category,
            )


class SettingsScreen(BasePage):
    saved = pyqtSignal(object)
    theme_preview_requested = pyqtSignal(str)

    def __init__(
        self, settings: AppSettings, preview_path: Path | None = None, answer_status: str = ""
    ):
        super().__init__()
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ScrollArea cho SettingsScreen tương thích mọi độ phân giải (1100x700, 1280x800)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("settingsScrollArea")
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.content_widget = QWidget()
        self.content_widget.setObjectName("settingsContent")
        layout = QVBoxLayout(self.content_widget)
        layout.setContentsMargins(32, 24, 32, 32)
        layout.setSpacing(20)

        # Header back button & title
        top = QHBoxLayout()
        top.addWidget(self.back_button())
        title, subtitle = page_title("Cài đặt", "Tùy chỉnh giao diện, dữ liệu và vùng cắt đáp án.")
        heading = QVBoxLayout()
        heading.addWidget(title)
        heading.addWidget(subtitle)
        top.addLayout(heading, 1)
        layout.addLayout(top)

        # Form card
        card = QFrame()
        card.setObjectName("card")
        form = QFormLayout(card)
        form.setContentsMargins(20, 16, 20, 16)
        form.setSpacing(12)

        self.theme = QComboBox()
        self.theme.addItem("Giống hệ thống", "system")
        self.theme.addItem("Sáng", "light")
        self.theme.addItem("Tối", "dark")
        index = self.theme.findData(settings.theme)
        self.theme.setCurrentIndex(max(0, index))
        self.theme.setToolTip(
            "Giống hệ thống tự dò giao diện Sáng/Tối của hệ điều hành."
        )
        self.theme.currentIndexChanged.connect(self._preview_theme)
        form.addRow("Giao diện", self.theme)

        path_widget = QWidget()
        path_layout = QHBoxLayout(path_widget)
        path_layout.setContentsMargins(0, 0, 0, 0)
        self.data_path = QLineEdit(settings.data_dir)
        browse = secondary(QPushButton("Chọn..."))
        browse.clicked.connect(self._browse)
        path_layout.addWidget(self.data_path)
        path_layout.addWidget(browse)
        form.addRow("Thư mục DATA", path_widget)

        self.crop_values: list[QDoubleSpinBox] = []
        labels = ("Crop X (%)", "Crop Y (%)", "Crop rộng (%)", "Crop cao (%)")
        for label, value in zip(labels, settings.crop_region):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 100.0)
            spin.setDecimals(1)
            spin.setValue(value * 100.0)
            self.crop_values.append(spin)
            form.addRow(label, spin)
            spin.valueChanged.connect(self._update_preview_crop)

        if answer_status:
            status = QLabel(answer_status)
            status.setWordWrap(True)
            form.addRow("Trạng thái đáp án", status)

        layout.addWidget(card)

        # Preview Section (LUÔN hiển thị section)
        preview_label = QLabel("Xem trước ảnh sau khi cắt đáp án")
        preview_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(preview_label)

        self.preview: QuestionImageViewer | None = None
        self.placeholder_frame: QFrame | None = None

        loaded_successfully = False
        if preview_path is not None and preview_path.is_file():
            self.preview = QuestionImageViewer()
            self.preview.setMinimumHeight(320)
            self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            try:
                self.preview.load_image(preview_path)
                self._update_preview_crop()
                layout.addWidget(self.preview, 1)
                loaded_successfully = True
            except (OSError, ValueError):
                self.preview = None

        if not loaded_successfully:
            # Khung placeholder hiển thị thông báo rõ ràng khi không tìm thấy ảnh
            self.placeholder_frame = QFrame()
            self.placeholder_frame.setObjectName("settingsPreviewPlaceholder")
            self.placeholder_frame.setMinimumHeight(200)
            self.placeholder_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            p_layout = QVBoxLayout(self.placeholder_frame)
            p_layout.setAlignment(Qt.AlignCenter)
            p_text = QLabel("Không tìm thấy ảnh để xem trước.\nHãy kiểm tra thư mục DATA hoặc chọn lại thư mục dữ liệu.")
            p_text.setObjectName("settingsPreviewPlaceholderText")
            p_text.setAlignment(Qt.AlignCenter)
            p_layout.addWidget(p_text)
            layout.addWidget(self.placeholder_frame)

        # Save button ở góc dưới-phải
        save_layout = QHBoxLayout()
        save_layout.addStretch(1)
        self.save_button = QPushButton("Lưu cài đặt")
        self.save_button.setObjectName("settingsSaveButton")
        self.save_button.setFixedHeight(40)
        self.save_button.setMinimumWidth(132)
        self.save_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.save_button.clicked.connect(self._save)
        save_layout.addWidget(self.save_button, alignment=Qt.AlignVCenter)

        layout.addLayout(save_layout)

        self.scroll_area.setWidget(self.content_widget)
        root_layout.addWidget(self.scroll_area)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục DATA", self.data_path.text())
        if path:
            self.data_path.setText(path)

    def _preview_theme(self, _index: int) -> None:
        self.theme_preview_requested.emit(str(self.theme.currentData()))

    def _update_preview_crop(self) -> None:
        if self.preview is not None:
            self.preview.set_crop_region(
                tuple(spin.value() / 100.0 for spin in self.crop_values)
            )

    def _save(self) -> None:
        values = [spin.value() / 100.0 for spin in self.crop_values]
        x, y, width, height = values
        if width <= 0 or height <= 0 or x + width > 1.0 or y + height > 1.0:
            QMessageBox.warning(
                self, "Vùng crop chưa hợp lệ", "Vùng crop phải nằm hoàn toàn bên trong ảnh."
            )
            return
        settings = AppSettings(
            theme=str(self.theme.currentData()),
            data_dir=self.data_path.text().strip(),
            mask_x=x,
            mask_y=y,
            mask_width=width,
            mask_height=height,
        )
        self.saved.emit(settings)


class HistoryScreen(BasePage):
    delete_requested = pyqtSignal(list)

    def __init__(self, history: list[dict]):
        super().__init__()
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self.back_button())
        title, _ = page_title("Lịch sử bài thi")
        top.addWidget(title)
        top.addStretch()
        self.delete_button = QPushButton("🗑️ Xóa bài thi")
        self.delete_button.setObjectName("deleteExamButton")
        self.delete_button.setProperty("danger", True)
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._request_delete)
        top.addWidget(self.delete_button)
        layout.addLayout(top)
        self.tree = QTreeWidget()
        self.tree.setObjectName("examHistoryTree")
        self.tree.setHeaderLabels(["Môn học / Bài thi", "Kết quả", "Thời gian"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setIndentation(24)
        self.tree.itemSelectionChanged.connect(self._update_delete_button)
        layout.addWidget(self.tree, 1)
        if not history:
            empty = QTreeWidgetItem(["Chưa có bài thi nào", "", ""])
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            self.tree.addTopLevelItem(empty)
        subject_nodes: dict[str, QTreeWidgetItem] = {}
        for attempt in history:
            subject = str(attempt["subject"])
            parent = subject_nodes.get(subject)
            if parent is None:
                parent = QTreeWidgetItem([f"📁 Môn học: {subject}", "", ""])
                parent.setFlags(parent.flags() & ~Qt.ItemIsSelectable)
                parent_font = parent.font(0)
                parent_font.setBold(True)
                for column in range(3):
                    parent.setFont(column, parent_font)
                    parent.setBackground(column, QColor("#D8DCE3"))
                    parent.setForeground(column, QColor("#1D1D1F"))
                self.tree.addTopLevelItem(parent)
                self.tree.setFirstItemColumnSpanned(parent, True)
                parent.setExpanded(True)
                subject_nodes[subject] = parent
            exam_item = QTreeWidgetItem(
                [
                    f"Bài thi #{attempt['id']}",
                    f"{attempt['score']:.2f}/10 ({attempt['score_percent']:.2f}%)",
                    self._format_submitted_at(attempt["submitted_at"]),
                ]
            )
            exam_item.setData(0, Qt.UserRole, int(attempt["id"]))
            parent.addChild(exam_item)

    @staticmethod
    def _format_submitted_at(value: object) -> str:
        raw_value = str(value).strip()
        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone().strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return raw_value

    def selected_attempt_ids(self) -> list[int]:
        attempt_ids = {
            int(item.data(0, Qt.UserRole))
            for item in self.tree.selectedItems()
            if item.parent() is not None and item.data(0, Qt.UserRole) is not None
        }
        return sorted(attempt_ids)

    def _update_delete_button(self) -> None:
        self.delete_button.setEnabled(bool(self.selected_attempt_ids()))

    def _request_delete(self) -> None:
        attempt_ids = self.selected_attempt_ids()
        if attempt_ids:
            self.delete_requested.emit(attempt_ids)
