from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication

from app.ui.brand_icon import (
    ANIMATION_DURATION_MS,
    LETTER_PATHS,
    StartupSplash,
    application_icon,
    render_brand_icon,
)

QT_APP = QApplication.instance() or QApplication([])


def _warm_pixels(image) -> int:
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if (color := image.pixelColor(x, y)).alpha() > 200
        and color.red() > 190
        and color.red() > color.blue() * 1.7
    )


def test_icon_has_real_transparency_and_visible_small_size() -> None:
    icon = render_brand_icon(32)
    assert icon.pixelColor(0, 0).alpha() == 0
    assert icon.pixelColor(16, 16).alpha() < 255
    assert any(icon.pixelColor(x, y).blue() > 70 for y in range(32) for x in range(32))
    assert not application_icon().pixmap(32, 32).isNull()


def test_animation_fills_then_drains_the_letters() -> None:
    initial = render_brand_icon(128, 0)
    full = render_brand_icon(128, 1200)
    final = render_brand_icon(128, ANIMATION_DURATION_MS)
    assert _warm_pixels(initial) == 0
    assert _warm_pixels(full) > 100
    assert _warm_pixels(final) == 0


def test_r_leg_joins_lower_c_curve() -> None:
    r_foot = LETTER_PATHS[2].currentPosition()
    c = LETTER_PATHS[3]
    closest = min(
        (r_foot - c.pointAtPercent(index / 200)).manhattanLength()
        for index in range(201)
    )
    assert closest < 1.0


def test_splash_completes_and_closes() -> None:
    splash = StartupSplash()
    signal = QSignalSpy(splash.finished)
    splash.show()
    splash.start()
    QTest.qWait(ANIMATION_DURATION_MS + 100)
    assert len(signal) == 1
    assert not splash.isVisible()
