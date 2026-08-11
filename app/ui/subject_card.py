from __future__ import annotations

import re

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QCursor,
    QFocusEvent,
    QFontMetrics,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import Subject
from app.ui.icons import create_line_icon


def extract_monogram(name: str) -> str:
    """Tạo monogram 3 chữ cái in hoa đại diện môn học (VD: ITE303c -> ITE, MAS291 -> MAS)."""
    alpha_chars = re.sub(r"[^A-Za-z]", "", name).upper()
    if len(alpha_chars) >= 3:
        return alpha_chars[:3]
    if len(alpha_chars) > 0:
        return alpha_chars
    return "SUB"


class MonogramTile(QWidget):
    """Tile monogram góc bo tròn với gradient chuyển màu nhẹ."""

    def __init__(self, monogram: str, parent=None):
        super().__init__(parent)
        self.monogram = monogram
        self.setFixedSize(80, 80)

    def set_monogram(self, text: str) -> None:
        self.monogram = text
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(self.rect())
        radius = 18.0

        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor("#3B82F6"))
        gradient.setColorAt(1.0, QColor("#8B5CF6"))

        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, radius, radius)

        # Dynamic Font Scaling với QFontMetrics để 3 chữ cái không bị clipping
        max_target_width = self.width() - 16.0  # Lề ngang tối thiểu 8px mỗi bên
        start_size = 25 if len(self.monogram) >= 3 else 30

        font = painter.font()
        font.setBold(True)

        for size in range(start_size, 12, -1):
            font.setPixelSize(size)
            metrics = QFontMetrics(font)
            if metrics.horizontalAdvance(self.monogram) <= max_target_width:
                break

        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(rect, Qt.AlignCenter, self.monogram)
        painter.end()


class SubjectCard(QFrame):
    """Widget Card môn học Liquid Glass macOS Tahoe 26.

    Tất cả bóng mờ (shadow) được vẽ trực tiếp trong vùng đệm của widget bounds
    để tuyệt đối không bị clipping hình chữ nhật bởi parent container / scroll viewport.
    """

    selected = pyqtSignal(str)

    def __init__(self, subject: Subject | None = None, parent=None):
        super().__init__(parent)
        self.subject = subject
        self.is_hovered = False
        self.is_pressed = False

        self.setObjectName("subjectCard")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(236)
        self.setMinimumWidth(340)
        self.setMaximumWidth(440)

        # Layout chính (căn lề theo body_rect nội bộ)
        # Offset lề: trái 14, trên 10, phải 14, dưới 18
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14 + 22, 10 + 18, 14 + 22, 18 + 16)
        main_layout.setSpacing(10)

        # Top Section: Monogram + Subject Info
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(16)

        self.monogram_tile = MonogramTile("")
        top_layout.addWidget(self.monogram_tile)

        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 2, 0, 2)
        info_layout.setSpacing(4)

        self.title_label = QLabel()
        self.title_label.setObjectName("subjectName")
        self.title_label.setWordWrap(True)

        self.count_label = QLabel()
        self.count_label.setObjectName("subjectCount")

        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.count_label)
        info_layout.addStretch(1)

        top_layout.addLayout(info_layout, 1)
        main_layout.addLayout(top_layout)

        # Bottom Section: CTA + Right Arrow
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 4, 0, 0)

        self.cta_label = QLabel("Tiếp tục học")
        self.cta_label.setObjectName("subjectAction")

        self.arrow_label = QLabel()
        self.arrow_label.setObjectName("subjectArrow")
        self.arrow_label.setFixedSize(24, 24)

        bottom_layout.addWidget(self.cta_label)
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.arrow_label)

        main_layout.addLayout(bottom_layout)

        if subject:
            self.set_subject(subject)

    def set_subject(self, subject: Subject) -> None:
        self.subject = subject
        monogram = extract_monogram(subject.name)
        self.monogram_tile.set_monogram(monogram)
        self.title_label.setText(subject.name)
        self.title_label.setToolTip(subject.name)
        self.count_label.setText(f"{subject.question_count} câu hỏi")
        self.setAccessibleName(f"Môn học {subject.name}, {subject.question_count} câu hỏi")
        self.update_theme()

    def update_theme(self) -> None:
        app = QApplication.instance()
        is_dark = (app and app.property("appliedTheme") == "dark")
        color = QColor("#60A5FA") if is_dark else QColor("#0A84FF")
        icon = create_line_icon("arrow_right", size=24, color=color, stroke_width=2.2)
        self.arrow_label.setPixmap(icon.pixmap(24, 24))
        self.update()

    def enterEvent(self, event) -> None:
        self.is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.is_hovered = False
        self.is_pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.is_pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self.is_pressed:
            self.is_pressed = False
            self.update()
            if self.rect().contains(event.pos()) and self.subject:
                self.selected.emit(self.subject.name)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self.subject:
            self.selected.emit(self.subject.name)
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.update()
        super().focusOutEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(self.rect())
        # Body rect nằm thụt vào bên trong để chừa vùng đệm vẽ bóng mờ lan tỏa mượt mà
        body_rect = rect.adjusted(14.0, 10.0, -14.0, -18.0)
        radius = 22.0

        app = QApplication.instance()
        is_dark = (app and app.property("appliedTheme") == "dark")

        # Dùng cùng silhouette cho body và phép loại trừ shadow ở Light Mode.
        # Khi glass fill có alpha thấp, shadow nằm dưới interior sẽ xuyên qua
        # và nhuộm card thành xám. Nhánh Dark giữ cách render trước đó.
        body_path = QPainterPath()
        body_path.addRoundedRect(body_rect, radius, radius)

        # 1. Vẽ bóng mờ (Soft Drop Shadow) mềm mại theo đúng silhouette bo góc
        if is_dark:
            shadow_base = QColor(0, 0, 0, 75) if not self.is_hovered else QColor(0, 0, 0, 110)
            shadow_layers = [
                (QPointF(0, 8.0), 4.0, 0.35),
                (QPointF(0, 5.0), 2.0, 0.55),
                (QPointF(0, 2.0), 0.0, 0.85),
            ]
        else:
            shadow_base = QColor(25, 40, 70, 58) if not self.is_hovered else QColor(15, 35, 80, 75)
            shadow_layers = [
                (QPointF(0, 10.0), 4.0, 0.35),
                (QPointF(0, 6.0), 2.0, 0.55),
                (QPointF(0, 2.0), 0.0, 0.85),
            ]

        for offset, expand, alpha_scale in shadow_layers:
            s_rect = body_rect.translated(offset).adjusted(-expand, -expand, expand, expand)
            c = QColor(shadow_base)
            c.setAlpha(int(shadow_base.alpha() * alpha_scale))
            s_path = QPainterPath()
            s_path.addRoundedRect(s_rect, radius + expand, radius + expand)
            shadow_path = s_path if is_dark else s_path.subtracted(body_path)
            painter.fillPath(shadow_path, c)

        # 2. Liquid Glass Body Fill
        if is_dark:
            gradient = QLinearGradient(body_rect.topLeft(), body_rect.bottomLeft())
            top_color = QColor(28, 34, 50, 195) if not self.is_hovered else QColor(36, 44, 64, 225)
            bot_color = QColor(18, 22, 34, 205) if not self.is_hovered else QColor(24, 30, 44, 230)
            gradient.setColorAt(0.0, top_color)
            gradient.setColorAt(1.0, bot_color)

            border_color = QColor(255, 255, 255, 30) if not self.hasFocus() else QColor(10, 132, 255, 200)
            top_highlight_color = QColor(255, 255, 255, 35)
            divider_color = QColor(255, 255, 255, 20)
        else:
            gradient = QLinearGradient(body_rect.topLeft(), body_rect.bottomLeft())
            # 1.5x Transparency: Default top 115 / bot 132, Hover top 145 / bot 160
            top_color = QColor(255, 255, 255, 115) if not self.is_hovered else QColor(255, 255, 255, 145)
            bot_color = QColor(246, 249, 254, 132) if not self.is_hovered else QColor(250, 252, 255, 160)
            gradient.setColorAt(0.0, top_color)
            gradient.setColorAt(1.0, bot_color)

            border_color = QColor(95, 110, 135, 60) if not self.hasFocus() else QColor(10, 132, 255, 200)
            top_highlight_color = QColor(255, 255, 255, 220)
            divider_color = QColor(0, 0, 0, 16)

        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawPath(body_path)

        # 3. Glass Border
        border_pen = QPen(border_color, 1.5 if self.hasFocus() else 1.0)
        painter.setPen(border_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(body_path)

        # 4. Micro Top Highlight
        top_line_path = QPainterPath()
        top_line_path.moveTo(body_rect.left() + radius, body_rect.top() + 1.0)
        top_line_path.lineTo(body_rect.right() - radius, body_rect.top() + 1.0)
        painter.setPen(QPen(top_highlight_color, 1.0))
        painter.drawPath(top_line_path)

        # 5. Divider Line giữa phần thông tin và CTA
        divider_y = body_rect.bottom() - 48.0
        painter.setPen(QPen(divider_color, 1.0))
        painter.drawLine(
            QPointF(body_rect.left() + 22.0, divider_y),
            QPointF(body_rect.right() - 22.0, divider_y)
        )

        # 6. Focus Ring nếu đang được chọn qua bàn phím
        if self.hasFocus():
            focus_pen = QPen(QColor("#0A84FF"), 2.0)
            focus_rect = body_rect.adjusted(-2, -2, 2, 2)
            focus_path = QPainterPath()
            focus_path.addRoundedRect(focus_rect, radius + 2, radius + 2)
            painter.setPen(focus_pen)
            painter.drawPath(focus_path)

        painter.end()
