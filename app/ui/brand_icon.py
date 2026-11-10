"""SRC Learning icon artwork and the short, cross-platform launch animation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PyQt5.QtCore import QElapsedTimer, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt5.QtWidgets import QWidget

ICON_PATH = Path(__file__).resolve().parents[1] / "resources" / "brand" / "src-learning-256.png"
ANIMATION_DURATION_MS = 2500


def _letter_paths() -> tuple[QPainterPath, ...]:
    """Centerlines, ordered from the lower end of S through R to the end of C."""
    s = QPainterPath()
    s.moveTo(84, 324)
    s.cubicTo(104, 352, 137, 361, 164, 340)
    s.cubicTo(190, 320, 184, 278, 148, 263)
    s.lineTo(112, 248)
    s.cubicTo(72, 231, 55, 200, 82, 176)
    s.cubicTo(107, 151, 143, 158, 165, 180)

    r = QPainterPath()
    r.moveTo(215, 260)
    r.lineTo(215, 162)
    r.lineTo(270, 162)
    r.cubicTo(308, 162, 329, 183, 329, 218)
    r.cubicTo(329, 245, 307, 253, 270, 253)
    r.lineTo(215, 253)

    r_leg = QPainterPath()
    # A short, level shoulder gives R its own leg before it naturally flows
    # into the lowest curve of C, as in the reference mark.
    r_leg.moveTo(248, 288)
    r_leg.cubicTo(286, 284, 320, 346, 366, 350)

    c = QPainterPath()
    c.moveTo(437, 181)
    c.cubicTo(414, 161, 389, 155, 365, 163)
    c.cubicTo(324, 176, 314, 214, 314, 256)
    c.cubicTo(314, 300, 326, 337, 366, 350)
    c.cubicTo(392, 358, 419, 349, 440, 331)
    return s, r, r_leg, c


LETTER_PATHS = _letter_paths()
PATH_LENGTHS = tuple(path.length() for path in LETTER_PATHS)
TOTAL_PATH_LENGTH = sum(PATH_LENGTHS)


@lru_cache(maxsize=1)
def _mark_masks() -> tuple[QImage, QImage, QImage, QImage, QImage]:
    directory = ICON_PATH.parent
    names = ("src-logo-mask.png", "src-logo-interior.png",
             "src-logo-rim.png", "src-logo-glow.png", "src-logo-small.png")
    masks = tuple(QImage(str(directory / name)) for name in names)
    if any(mask.isNull() for mask in masks):
        raise FileNotFoundError("SRC logo masks are missing; run tools/build_app_icon.py")
    return masks


def _mix(a: QColor, b: QColor, amount: float) -> QColor:
    amount = max(0.0, min(1.0, amount))
    return QColor(
        round(a.red() + (b.red() - a.red()) * amount),
        round(a.green() + (b.green() - a.green()) * amount),
        round(a.blue() + (b.blue() - a.blue()) * amount),
        round(a.alpha() + (b.alpha() - a.alpha()) * amount),
    )


def _partial_path(path: QPainterPath, distance: float) -> QPainterPath:
    length = path.length()
    if distance >= length:
        return path
    portion = QPainterPath()
    if distance <= 0:
        return portion
    steps = max(2, round(120 * distance / length))
    portion.moveTo(path.pointAtPercent(0))
    for step in range(1, steps + 1):
        ratio = path.percentAtLength(distance * step / steps)
        portion.lineTo(path.pointAtPercent(ratio))
    return portion


def _tint_mask(mask: QImage, color: QColor | QLinearGradient) -> QImage:
    tinted = QImage(512, 512, QImage.Format_ARGB32_Premultiplied)
    tinted.fill(Qt.transparent)
    painter = QPainter(tinted)
    painter.drawImage(0, 0, mask)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(QRectF(0, 0, 512, 512), QBrush(color))
    painter.end()
    return tinted


def _flow_mask(interior: QImage, flow: float) -> QImage:
    if flow >= 1.0:
        return interior
    progress = QImage(512, 512, QImage.Format_ARGB32_Premultiplied)
    progress.fill(Qt.transparent)
    painter = QPainter(progress)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(256, 256)
    painter.scale(1.1, 1.4)
    painter.translate(-256, -256)
    painter.setPen(QPen(Qt.white, 70, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    remaining = flow * TOTAL_PATH_LENGTH
    for path, length in zip(LETTER_PATHS, PATH_LENGTHS):
        if remaining <= 0:
            break
        painter.drawPath(_partial_path(path, remaining))
        remaining -= length
    painter.resetTransform()
    painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, interior)
    painter.end()
    return progress


def _paint_glass(painter: QPainter) -> None:
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(17, 17, 478, 478), 111, 111)
    glass = QLinearGradient(36, 29, 465, 479)
    glass.setColorAt(0, QColor(255, 255, 255, 108))
    glass.setColorAt(0.5, QColor(225, 242, 255, 59))
    glass.setColorAt(1, QColor(122, 181, 225, 75))
    painter.fillPath(tile, glass)

    rim = QLinearGradient(34, 25, 470, 480)
    rim.setColorAt(0, QColor(255, 255, 255, 224))
    rim.setColorAt(0.48, QColor(255, 255, 255, 43))
    rim.setColorAt(1, QColor(33, 91, 135, 124))
    painter.setPen(QPen(QBrush(rim), 3))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(tile)

    highlight = QPainterPath()
    highlight.moveTo(55, 209)
    highlight.cubicTo(59, 116, 123, 55, 217, 52)
    painter.setPen(QPen(QColor(255, 255, 255, 106), 5, Qt.SolidLine, Qt.RoundCap))
    painter.drawPath(highlight)


def paint_brand_icon(painter: QPainter, rect: QRectF, elapsed_ms: int | None = None) -> None:
    """Paint a glass icon; elapsed_ms=None paints the final static state."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(rect.left(), rect.top())
    painter.scale(rect.width() / 512.0, rect.height() / 512.0)
    _paint_glass(painter)

    if elapsed_ms is None:
        blue_mix, flow, liquid_alpha, glow = 1.0, 0.0, 0.0, 0.0
    else:
        elapsed = max(0, min(ANIMATION_DURATION_MS, elapsed_ms))
        flow = min(1.0, elapsed / 1200.0)
        blue_mix = max(0.0, min(1.0, (elapsed - 1200) / 600.0))
        liquid_alpha = max(0.0, min(1.0, (2500 - elapsed) / 700.0))
        glow = max(0.0, 1.0 - abs(elapsed - 1500) / 300.0)

    mark, interior, rim, glow_mask, small = _mark_masks()
    blue = QColor("#0D5689")
    if elapsed_ms is None:
        painter.drawImage(0, 0, _tint_mask(small if rect.width() <= 64 else mark, blue))
        painter.restore()
        return
    if glow:
        painter.setOpacity(glow * 0.35)
        painter.drawImage(0, 0, _tint_mask(glow_mask, QColor("#2490F2")))
        painter.setOpacity(1.0)

    painter.drawImage(0, 0, _tint_mask(rim, _mix(QColor("#FFFFFF"), blue, blue_mix)))
    if blue_mix:
        painter.setOpacity(blue_mix)
        painter.drawImage(0, 0, _tint_mask(interior, blue))
        painter.setOpacity(1.0)

    if flow > 0 and liquid_alpha > 0:
        gradient = QLinearGradient(65, 360, 455, 160)
        gradient.setColorAt(0, QColor("#FFA437"))
        gradient.setColorAt(0.55, QColor("#FF652B"))
        gradient.setColorAt(1, QColor("#DE3537"))
        painter.setOpacity(liquid_alpha)
        painter.drawImage(0, 0, _tint_mask(_flow_mask(interior, flow), gradient))
        painter.setOpacity(1.0)
    painter.restore()


def render_brand_icon(size: int, elapsed_ms: int | None = None) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    paint_brand_icon(painter, QRectF(0, 0, size, size), elapsed_ms)
    painter.end()
    return image


def application_icon() -> QIcon:
    icon = QIcon(str(ICON_PATH))
    if icon.isNull():
        icon.addPixmap(QPixmap.fromImage(render_brand_icon(256)))
    return icon


class StartupSplash(QWidget):
    """Animated icon shown once while handing launch over to the main window."""

    finished = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(400, 400)
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)

    def start(self) -> None:
        self._clock.start()
        self._timer.start()
        self.update()

    def _advance(self) -> None:
        if self._clock.elapsed() >= ANIMATION_DURATION_MS:
            self._timer.stop()
            self.finished.emit()
            self.close()
        else:
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        paint_brand_icon(painter, QRectF(0, 0, self.width(), self.height()),
                         self._clock.elapsed() if self._clock.isValid() else 0)
        painter.end()
