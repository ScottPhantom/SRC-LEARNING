from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PyQt5.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

# Cached background image pixmap
_HOME_LIGHT_PIXMAP: QPixmap | None = None
_HOME_LIGHT_LOADED: bool = False

LIGHT_HOME_BG_ASSET = "app/ui/assets/backgrounds/light/pexels-codioful-7130573.jpg"


def resolve_resource_path(relative_path: str | Path) -> Path:
    """Resolve a resource path for source execution, pytest, and PyInstaller bundles.

    Supports:
    - Running directly (python main.py)
    - Running via pytest
    - Running from any current working directory
    - PyInstaller standalone build (one-folder / one-file via sys._MEIPASS)
    """
    rel = Path(relative_path)

    # 1. PyInstaller frozen environment (_MEIPASS)
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundle_dir = Path(sys._MEIPASS)
        bundle_path = bundle_dir / rel
        if bundle_path.exists():
            return bundle_path

    # 2. Source execution relative to project root (parent of 'app')
    project_root = Path(__file__).resolve().parent.parent.parent
    source_path = project_root / rel
    if source_path.exists():
        return source_path

    # 3. Fallback relative to CWD
    cwd_path = Path.cwd() / rel
    if cwd_path.exists():
        return cwd_path

    return source_path


def get_home_light_pixmap() -> QPixmap | None:
    """Lazy load and cache the Home Light Mode background pixmap."""
    global _HOME_LIGHT_PIXMAP, _HOME_LIGHT_LOADED
    if _HOME_LIGHT_LOADED:
        return _HOME_LIGHT_PIXMAP

    _HOME_LIGHT_LOADED = True
    asset_path = resolve_resource_path(LIGHT_HOME_BG_ASSET)

    if asset_path.is_file():
        pixmap = QPixmap(str(asset_path))
        if not pixmap.isNull():
            _HOME_LIGHT_PIXMAP = pixmap
            return _HOME_LIGHT_PIXMAP

    logger.warning("Could not load Light Home background asset at: %s", asset_path)
    _HOME_LIGHT_PIXMAP = None
    return None


def is_dark_theme() -> bool:
    """Return the theme that is currently applied to the QApplication."""
    application = QApplication.instance()
    return bool(application and application.property("appliedTheme") == "dark")


def paint_app_background(
    painter: QPainter,
    rect: QRectF,
    dark: bool | None = None,
    variant: str = "default",
) -> None:
    """Paint the resize-safe ambient background for app screens.

    Variants:
    - 'default': Shared ambient radial gradient (for BasePage screens).
    - 'home': Main Screen background (uses asset image in Light Mode, dark gradient in Dark Mode).
    """
    if rect.isEmpty():
        return

    dark = is_dark_theme() if dark is None else dark
    width = rect.width()
    height = rect.height()
    radius = max(width, height)

    if dark:
        painter.fillRect(rect, QColor("#0E0F12"))
        navy = QRadialGradient(
            QPointF(rect.left() + width * 0.45, rect.top() + height * 0.35),
            radius * 0.68,
        )
        navy.setColorAt(0.0, QColor(21, 36, 69, 125))
        navy.setColorAt(0.66, QColor(21, 36, 69, 24))
        navy.setColorAt(1.0, Qt.transparent)
        painter.fillRect(rect, navy)
        return

    # Light Mode
    if variant == "home":
        pixmap = get_home_light_pixmap()
        if pixmap and not pixmap.isNull():
            iw = float(pixmap.width())
            ih = float(pixmap.height())
            if iw > 0 and ih > 0 and width > 0 and height > 0:
                # Cover & Center-Crop calculation
                scale = min(iw / width, ih / height)
                crop_w = width * scale
                crop_h = height * scale
                src_x = (iw - crop_w) / 2.0
                src_y = (ih - crop_h) / 2.0
                src_rect = QRectF(src_x, src_y, crop_w, crop_h)

                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                painter.drawPixmap(rect, pixmap, src_rect)
                return

    # Default Light Mode ambient gradient (also fallback for home if image missing/invalid)
    base = QLinearGradient(rect.topLeft(), rect.bottomRight())
    base.setColorAt(0.0, QColor("#FAFBFD"))
    base.setColorAt(1.0, QColor("#EEF3FA"))
    painter.fillRect(rect, base)

    glows = (
        (0.25, 0.18, 0.55, QColor(215, 195, 245, 52)),
        (0.52, 0.42, 0.60, QColor(185, 215, 255, 58)),
        (0.78, 0.22, 0.50, QColor(245, 205, 225, 48)),
    )
    for x_ratio, y_ratio, radius_ratio, color in glows:
        glow = QRadialGradient(
            QPointF(
                rect.left() + width * x_ratio,
                rect.top() + height * y_ratio,
            ),
            radius * radius_ratio,
        )
        glow.setColorAt(0.0, color)
        glow.setColorAt(0.70, QColor(color.red(), color.green(), color.blue(), 10))
        glow.setColorAt(1.0, Qt.transparent)
        painter.fillRect(rect, glow)


class AppBackgroundCanvas(QWidget):
    """Reusable canvas used where a screen needs a scrollable background surface."""

    def __init__(self, parent: QWidget | None = None, variant: str = "default"):
        super().__init__(parent)
        self.variant = variant
        self.setObjectName("appBackgroundCanvas")
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        paint_app_background(painter, QRectF(self.rect()), variant=self.variant)
        painter.end()


class AppShell(QWidget):
    """Container chính của ứng dụng quản lý lớp nền continuous background đằng sau header và content stack."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("appShell")
        self.home_background_active = True
        self.setProperty("homeBackgroundActive", "true")
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def set_home_background_active(self, active: bool) -> None:
        if self.home_background_active != active:
            self.home_background_active = active
            self.setProperty("homeBackgroundActive", "true" if active else "false")
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        app = QApplication.instance()
        is_dark = (app and app.property("appliedTheme") == "dark")

        if self.home_background_active and not is_dark:
            paint_app_background(painter, QRectF(self.rect()), dark=False, variant="home")
        else:
            paint_app_background(painter, QRectF(self.rect()), dark=is_dark, variant="default")
        painter.end()
