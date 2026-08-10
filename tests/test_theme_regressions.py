from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QApplication, QWidget

from app.domain.models import AppSettings
from app.ui.background import AppBackgroundCanvas, paint_app_background
from app.ui.screens import BasePage, SettingsScreen
from app.ui.subject_card import SubjectCard
from app.ui.themes import DARK_STYLE, LIGHT_STYLE, ThemeManager

APP = QApplication.instance() or QApplication([])


def test_settings_save_button_keeps_a_visible_primary_role() -> None:
    ThemeManager(APP).apply("light")
    screen = SettingsScreen(AppSettings(theme="light"))
    screen.resize(900, 700)
    screen.show()
    APP.processEvents()

    assert screen.save_button.objectName() == "settingsSaveButton"
    assert screen.save_button.isEnabled()
    assert screen.save_button.height() == 40
    assert screen.save_button.minimumWidth() >= 132
    assert "QPushButton#settingsSaveButton" in LIGHT_STYLE
    assert "QPushButton#settingsSaveButton" in DARK_STYLE
    rendered_button = screen.save_button.grab().toImage()
    assert rendered_button.pixelColor(10, 20) == QColor("#0A84FF")
    screen.close()
    screen.deleteLater()


def test_shared_background_renders_and_switches_theme_without_error() -> None:
    manager = ThemeManager(APP)
    canvas = AppBackgroundCanvas()
    page = BasePage()
    canvas.resize(320, 200)
    page.resize(320, 200)

    images = []
    for theme in ("light", "dark"):
        manager.apply(theme)
        canvas.update()
        page.update_theme()
        image = QImage(320, 200, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        paint_app_background(painter, image.rect())
        painter.end()
        images.append(image.pixelColor(0, 0))

    assert images[0].lightness() > images[1].lightness()
    canvas.deleteLater()
    page.deleteLater()


def test_light_subject_card_shadow_does_not_dark_tint_glass_interior() -> None:
    """Shadow may surround translucent glass, but must not sit below its interior."""
    ThemeManager(APP).apply("light")
    host = QWidget()
    host.setObjectName("glassRegressionHost")
    host.setStyleSheet(
        "QWidget#glassRegressionHost { background: rgb(227, 209, 137); }"
    )
    host.resize(460, 270)

    card = SubjectCard(parent=host)
    card.setFixedWidth(400)
    card.move(20, 10)
    host.show()
    APP.processEvents()

    rendered = host.grab().toImage()
    background = rendered.pixelColor(5, 5)
    glass_interior = rendered.pixelColor(320, 150)

    # A translucent white fill must lighten every background channel. If the
    # layered shadow is still painted below the body, red/green become darker.
    assert glass_interior.red() >= background.red()
    assert glass_interior.green() >= background.green()
    assert glass_interior.blue() >= background.blue()

    host.close()
    host.deleteLater()


def test_home_light_mode_background_no_charcoal_and_attributes(tmp_path) -> None:
    from PyQt5.QtCore import Qt

    from app.controllers import MainWindow
    from app.repositories.database import Database

    db = Database(tmp_path / "test.sqlite3")
    window = MainWindow(db)
    window.resize(1280, 800)
    window.settings.theme = "light"
    window._apply_theme("light")
    window.show()
    APP.processEvents()

    home = window.home
    # 1. Kiểm tra attributes của canvas và viewport
    assert not home.canvas.testAttribute(Qt.WA_OpaquePaintEvent)
    assert home.canvas.testAttribute(Qt.WA_TranslucentBackground)
    assert not home.scroll_area.viewport().autoFillBackground()
    assert home.scroll_area.viewport().testAttribute(Qt.WA_TranslucentBackground)

    # 2. Render thực tế và lấy mẫu pixel ở vùng trống giữa màn hình (x=800, y=300)
    img = window.grab().toImage()
    sampled_color = img.pixelColor(800, 300)

    # Nền pastel ở Light Mode có độ sáng cao (lightness > 120, RGB đều > 100)
    # Tuyệt đối không được gần màu charcoal tối (#222222 -> R,G,B < 45)
    assert sampled_color.red() > 100
    assert sampled_color.green() > 100
    assert sampled_color.blue() > 100
    assert sampled_color.lightness() > 120

    # 3. Theme switching: Light -> Dark -> Light
    window.settings.theme = "dark"
    window._apply_theme("dark")
    APP.processEvents()
    dark_img = window.grab().toImage()
    dark_color = dark_img.pixelColor(800, 300)
    assert dark_color.lightness() < 50

    window.settings.theme = "light"
    window._apply_theme("light")
    APP.processEvents()
    light_again_img = window.grab().toImage()
    light_again_color = light_again_img.pixelColor(800, 300)
    assert light_again_color.lightness() > 120

    # 4. Navigation: Home -> Settings -> Home
    window.show_settings()
    APP.processEvents()
    assert not window.shell.home_background_active

    window.show_home()
    APP.processEvents()
    assert window.shell.home_background_active
    assert window.app_header.is_home_mode

    returned_img = window.grab().toImage()
    returned_color = returned_img.pixelColor(800, 300)
    assert returned_color.lightness() > 120

    # 5. Resize testing
    window.resize(1100, 700)
    APP.processEvents()
    r_img = window.grab().toImage()
    assert r_img.pixelColor(700, 300).lightness() > 120

    window.thread_pool.waitForDone(1500)
    window.close()
    db.close()
