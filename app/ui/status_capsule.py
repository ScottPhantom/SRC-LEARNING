from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class StatusDot(QWidget):
    """Dot hiển thị màu trạng thái dữ liệu dạng tròn nhỏ."""

    def __init__(self, color: QColor | None = None, parent=None):
        super().__init__(parent)
        self.color = QColor("#0A84FF") if color is None else color
        self.setFixedSize(8, 8)

    def set_color(self, color: QColor) -> None:
        self.color = color
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect())
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.color)
        painter.drawEllipse(rect)
        painter.end()


class StatusCapsule(QFrame):
    """Capsule hiển thị trạng thái dữ liệu (Liquid Glass Capsule)."""

    settings_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homeStatus")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setFixedHeight(32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 14, 4)
        layout.setSpacing(8)

        self.dot = StatusDot(QColor("#0A84FF"))

        self.label = QLabel("Đang quét dữ liệu…")
        self.label.setObjectName("statusText")
        font = self.label.font()
        font.setPixelSize(13)
        font.setWeight(QFont.Medium)
        self.label.setFont(font)

        self.action_button = QPushButton("Mở Cài đặt")
        self.action_button.setObjectName("statusActionButton")
        self.action_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.action_button.clicked.connect(self.settings_clicked)
        self.action_button.hide()

        layout.addWidget(self.dot)
        layout.addWidget(self.label)
        layout.addWidget(self.action_button)

    def set_data_ready(self, subject_count: int, data_dir: Path) -> None:
        self.dot.set_color(QColor("#0A84FF"))  # Accent Blue theo mockup đã duyệt
        môn_text = "môn học"
        self.label.setText(f"Dữ liệu đã sẵn sàng · {subject_count} {môn_text}")
        self.setToolTip(f"Đường dẫn dữ liệu: {data_dir.resolve()}")
        self.setAccessibleName(f"Dữ liệu đã sẵn sàng, {subject_count} môn học")
        self.action_button.hide()
        self.show()

    def set_loading(self, data_dir: Path) -> None:
        self.dot.set_color(QColor("#0A84FF"))
        self.label.setText("Đang quét dữ liệu…")
        self.setToolTip(f"Đang quét thư mục: {data_dir.resolve()}")
        self.setAccessibleName("Đang quét dữ liệu")
        self.action_button.hide()
        self.show()

    def set_empty(self, data_dir: Path) -> None:
        self.dot.set_color(QColor("#F59E0B"))  # Amber Warning
        self.label.setText("Chưa có môn học · Hãy thêm thư mục môn học vào DATA")
        self.setToolTip(f"Thư mục DATA trống: {data_dir.resolve()}")
        self.setAccessibleName("Chưa có môn học nào")
        self.action_button.hide()
        self.show()

    def set_missing_dir(self, data_dir: Path) -> None:
        self.dot.set_color(QColor("#EF4444"))  # Red Error
        self.label.setText(f"Không tìm thấy thư mục: {data_dir}")
        self.setToolTip(f"Không tìm thấy thư mục: {data_dir.resolve()}")
        self.setAccessibleName(f"Không tìm thấy thư mục {data_dir}")
        self.action_button.show()
        self.show()

    def set_error(self, message: str) -> None:
        self.dot.set_color(QColor("#EF4444"))
        self.label.setText(f"Lỗi: {message}")
        self.setToolTip(message)
        self.setAccessibleName(f"Lỗi quét dữ liệu: {message}")
        self.action_button.show()
        self.show()

    def setText(self, text: str) -> None:
        """API tương thích ngược cho main_controller (self.home.notice.setText)."""
        if "Không thể quét" in text or "Lỗi" in text or "lỗi" in text:
            self.set_error(text)
        elif "Không tìm thấy" in text:
            self.dot.set_color(QColor("#EF4444"))
            self.label.setText(text)
            self.action_button.show()
        elif "Đang quét" in text or "Đã tìm thấy" in text or "sẵn sàng" in text:
            self.dot.set_color(QColor("#0A84FF"))
            self.label.setText(text)
            self.action_button.hide()
        else:
            self.label.setText(text)
            self.action_button.hide()

    def text(self) -> str:
        return self.label.text()

    def update_theme(self) -> None:
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 16.0

        app = QApplication.instance()
        is_dark = (app and app.property("appliedTheme") == "dark")

        if is_dark:
            bg_color = QColor(28, 32, 44, 180)
            border_color = QColor(255, 255, 255, 25)
            painter.setPen(QPen(border_color, 1.0))
            painter.setBrush(bg_color)
            painter.drawRoundedRect(rect, radius, radius)
        else:
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)

            # 1. Soft shadow
            s_rect = rect.translated(0, 2.0).adjusted(-1, -1, 1, 1)
            s_path = QPainterPath()
            s_path.addRoundedRect(s_rect, radius + 1, radius + 1)
            outside_shadow_path = s_path.subtracted(path)
            painter.fillPath(outside_shadow_path, QColor(30, 40, 65, 28))

            # 2. Translucent Glass Fill (alpha 100 ~ 1.5x transparency)
            painter.fillPath(path, QColor(255, 255, 255, 100))

            # 3. Outer separation border
            painter.setPen(QPen(QColor(90, 105, 130, 55), 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

            # 4. Inner top highlight
            top_line = QPainterPath()
            top_line.moveTo(rect.left() + radius, rect.top() + 0.5)
            top_line.lineTo(rect.right() - radius, rect.top() + 0.5)
            painter.setPen(QPen(QColor(255, 255, 255, 210), 1.0))
            painter.drawPath(top_line)

        painter.end()
