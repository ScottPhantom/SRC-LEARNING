from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import ClassVar

from PIL import Image
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QImage, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QShortcut,
)


class QuestionImageViewer(QGraphicsView):
    """Viewer ảnh đã crop đáp án, có zoom tương đối so với chế độ fit."""

    answer_revealed = pyqtSignal()
    answer_hidden = pyqtSignal()
    answer_visibility_changed = pyqtSignal(bool)
    image_copied = pyqtSignal()
    _pixmap_cache: ClassVar[
        OrderedDict[tuple[str, int, tuple[float, float, float, float]], QPixmap]
    ] = OrderedDict()
    _cache_limit: ClassVar[int] = 24
    _zoom_factor = 1.20
    _min_zoom = -4
    _max_zoom = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setAlignment(Qt.AlignCenter)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setBackgroundBrush(QBrush(QColor("#dbe2ea")))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setSizeAdjustPolicy(QGraphicsView.AdjustIgnored)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._crop_region = (0.0, 0.90, 0.25, 0.10)
        self._answer_visible = False
        self._path: Path | None = None
        self._zoom_level = 0
        self._cropped_size = (0, 0)
        self._category = ""
        self._build_toolbar()
        self._build_copy_toast()
        self._build_category_notice()

    @property
    def answer_visible(self) -> bool:
        """Trạng thái logic đã yêu cầu hiện đáp án; ảnh vẫn luôn được crop."""
        return self._answer_visible

    @property
    def zoom_level(self) -> int:
        return self._zoom_level

    @property
    def cropped_size(self) -> tuple[int, int]:
        return self._cropped_size

    def _build_toolbar(self) -> None:
        # Toolbar là con trực tiếp của view (không phải scene/viewport), nên mọi
        # phép transform/scroll ảnh không thể thay đổi vị trí overlay.
        self.toolbar = QFrame(self)
        self.toolbar.setObjectName("imageToolbar")
        toolbar_layout = QHBoxLayout(self.toolbar)
        toolbar_layout.setContentsMargins(5, 5, 5, 5)
        toolbar_layout.setSpacing(4)
        self.zoom_in_button = QPushButton("+")
        self.reset_zoom_button = QPushButton("↻")
        self.zoom_out_button = QPushButton("−")
        self.copy_image_button = QPushButton("📋")
        for button, name in (
            (self.zoom_in_button, "Phóng to ảnh"),
            (self.reset_zoom_button, "Đưa ảnh về vừa màn hình"),
            (self.zoom_out_button, "Thu nhỏ ảnh"),
            (self.copy_image_button, "Sao chép ảnh vào Clipboard"),
        ):
            button.setObjectName("imageZoomButton")
            button.setFixedSize(32, 32)
            button.setToolTip(name)
            button.setAccessibleName(name)
            toolbar_layout.addWidget(button)
        self.zoom_out_button.clicked.connect(self.zoom_out)
        self.reset_zoom_button.clicked.connect(self.reset_zoom)
        self.zoom_in_button.clicked.connect(self.zoom_in)
        self.copy_image_button.clicked.connect(self.copy_image_to_clipboard)
        self.copy_image_button.setEnabled(False)

        # WindowShortcut giữ các thao tác ảnh hoạt động khi focus đang nằm ở
        # nút đáp án/sidebar khác trong cùng màn hình. Qt tự ánh xạ Ctrl thành
        # Command trên macOS theo QKeySequence.
        self.zoom_in_shortcuts: list[QShortcut] = []
        for sequence in ("Ctrl++", "Ctrl+="):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(self.zoom_in)
            self.zoom_in_shortcuts.append(shortcut)
        self.zoom_out_shortcut = QShortcut(QKeySequence("Ctrl+-"), self)
        self.zoom_out_shortcut.setContext(Qt.WindowShortcut)
        self.zoom_out_shortcut.activated.connect(self.zoom_out)
        self.copy_shortcut = QShortcut(QKeySequence.Copy, self)
        self.copy_shortcut.setContext(Qt.WindowShortcut)
        self.copy_shortcut.activated.connect(self.copy_image_to_clipboard)
        self.toolbar.adjustSize()
        self.toolbar.raise_()

    def _build_copy_toast(self) -> None:
        self.copy_toast = QLabel("Đã sao chép ảnh vào clipboard!", self)
        self.copy_toast.setObjectName("imageCopyToast")
        self.copy_toast.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.copy_toast.adjustSize()
        self.copy_toast.hide()
        self._copy_toast_timer = QTimer(self)
        self._copy_toast_timer.setSingleShot(True)
        self._copy_toast_timer.setInterval(1600)
        self._copy_toast_timer.timeout.connect(self.copy_toast.hide)

    def _build_category_notice(self) -> None:
        self.category_notice = QLabel(
            "Chú ý: Nhiều đáp án (Multiple_choose)", self
        )
        self.category_notice.setObjectName("multipleChoiceNotice")
        self.category_notice.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.category_notice.adjustSize()
        self.category_notice.hide()

    def set_question_category(self, category: str) -> None:
        self._category = category
        self.category_notice.setVisible(category == "Selections_Multiple_choose")
        self.category_notice.adjustSize()
        self._position_overlays()

    def set_crop_region(self, region: tuple[float, float, float, float]) -> None:
        normalized = tuple(max(0.0, min(1.0, float(value))) for value in region)
        if normalized == self._crop_region:
            return
        self._crop_region = normalized
        if self._path is not None:
            self.load_image(
                self._path,
                reveal=self._answer_visible,
                category=self._category,
            )

    def set_mask_region(self, region: tuple[float, float, float, float]) -> None:
        """Alias tương thích dữ liệu cài đặt cũ; không tạo lớp phủ."""
        self.set_crop_region(region)

    def load_image(
        self, path: Path, reveal: bool = False, category: str = ""
    ) -> None:
        self.scene().clear()
        self._pixmap_item = None
        self.copy_image_button.setEnabled(False)
        self.copy_toast.hide()
        self._copy_toast_timer.stop()
        self._path = Path(path)
        self.set_question_category(category)
        self._zoom_level = 0
        try:
            crop_key = tuple(round(value, 6) for value in self._crop_region)
            cache_key = (
                str(self._path.resolve()),
                self._path.stat().st_mtime_ns,
                crop_key,
            )
            pixmap = self._pixmap_cache.get(cache_key)
            if pixmap is None:
                with Image.open(path) as image:
                    rgba = image.convert("RGBA")
                    crop_bottom = self._crop_bottom(rgba.height)
                    rgba = rgba.crop((0, 0, rgba.width, crop_bottom))
                    self._cropped_size = rgba.size
                    data = rgba.tobytes("raw", "RGBA")
                    qt_image = QImage(
                        data,
                        rgba.width,
                        rgba.height,
                        rgba.width * 4,
                        QImage.Format_RGBA8888,
                    ).copy()
                    pixmap = QPixmap.fromImage(qt_image)
                self._pixmap_cache[cache_key] = pixmap
                while len(self._pixmap_cache) > self._cache_limit:
                    self._pixmap_cache.popitem(last=False)
            else:
                self._pixmap_cache.move_to_end(cache_key)
                self._cropped_size = (pixmap.width(), pixmap.height())
        except (OSError, ValueError) as exc:
            raise ValueError(f"Không đọc được ảnh {path.name}: {exc}") from exc
        if pixmap.isNull():
            raise ValueError(f"Không đọc được ảnh {path.name}")
        self._pixmap_item = self.scene().addPixmap(pixmap)
        self.copy_image_button.setEnabled(True)
        self.scene().setSceneRect(self._pixmap_item.boundingRect())
        self._answer_visible = reveal
        self._apply_zoom()
        self._position_overlays()

    def _crop_bottom(self, image_height: int) -> int:
        """Cắt toàn bộ dải đáy bắt đầu tại Y của vùng đáp án.

        Vùng OCR nằm sát cạnh dưới. Cắt cả dải ngang giữ ảnh chữ nhật, không tạo
        lỗ rỗng, không kéo giãn và bảo đảm ký tự đáp án không còn trong pixmap.
        """
        _x, y, _width, height = self._crop_region
        if height <= 0:
            return image_height
        return max(1, min(image_height, round(image_height * y)))

    def reveal_answer(self) -> None:
        if self._pixmap_item is None or self._answer_visible:
            return
        self._answer_visible = True
        self.answer_revealed.emit()
        self.answer_visibility_changed.emit(True)

    def hide_answer(self) -> None:
        if not self._answer_visible:
            return
        self._answer_visible = False
        self.answer_hidden.emit()
        self.answer_visibility_changed.emit(False)

    def toggle_answer(self) -> None:
        if self._answer_visible:
            self.hide_answer()
        else:
            self.reveal_answer()

    def zoom_in(self) -> None:
        if self._pixmap_item is not None and self._zoom_level < self._max_zoom:
            self._zoom_level += 1
            self._apply_zoom()

    def zoom_out(self) -> None:
        if self._pixmap_item is not None and self._zoom_level > self._min_zoom:
            self._zoom_level -= 1
            self._apply_zoom()

    def reset_zoom(self) -> None:
        self._zoom_level = 0
        self._apply_zoom()

    def copy_image_to_clipboard(self) -> bool:
        """Sao chép toàn bộ pixmap đã crop, không phụ thuộc zoom/scroll hiện tại."""
        if self._pixmap_item is None:
            return False
        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull():
            return False
        QApplication.clipboard().setPixmap(pixmap.copy())
        self.copy_toast.show()
        self.copy_toast.adjustSize()
        self._position_overlays()
        self._copy_toast_timer.start()
        self.image_copied.emit()
        return True

    def _apply_zoom(self) -> None:
        if self._pixmap_item is None:
            return
        self.resetTransform()
        self.fitInView(self._pixmap_item.boundingRect(), Qt.KeepAspectRatio)
        if self._zoom_level:
            factor = self._zoom_factor**self._zoom_level
            self.scale(factor, factor)
        self._position_overlays()

    def _position_overlays(self) -> None:
        margin = 12
        self.toolbar.adjustSize()
        self.toolbar.move(
            max(margin, self.width() - self.toolbar.width() - margin),
            margin,
        )
        self.category_notice.move(margin, margin)
        self.copy_toast.move(
            max(margin, self.width() - self.copy_toast.width() - margin),
            margin + self.toolbar.height() + 8,
        )
        self.toolbar.raise_()
        self.category_notice.raise_()
        self.copy_toast.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_zoom()
        self._position_overlays()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._position_overlays()
