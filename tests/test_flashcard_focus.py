from __future__ import annotations

import os
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton, QStyleFactory, QVBoxLayout, QWidget

from app.controllers import main_controller
from app.controllers.main_controller import MainWindow
from app.repositories.database import Database
from app.ui.screens import FlashcardScreen, ModeScreen
from app.ui.themes import ThemeManager
from tools.flashcard_release_qa import check_flash_profile, make_flash_profile


def wait_for(predicate):
    deadline = monotonic() + 5
    while not predicate():
        assert monotonic() < deadline, "Flashcard GUI state timed out"
        QTest.qWait(10)


@pytest.fixture(params=["Windows", "Fusion"])
def flash_window(request, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    if request.param not in QStyleFactory.keys():
        pytest.skip("Qt style unavailable")
    previous_style = app.style().objectName()
    app.setStyle(request.param)
    state = make_flash_profile(tmp_path)
    monkeypatch.setattr(main_controller, "STATE_DIR", tmp_path / "isolated-state")
    database = Database(state["database"])
    window = MainWindow(database)
    window.resize(1280, 800)
    window.show()
    window.activateWindow()
    wait_for(lambda: not window._scan_running and not window._rescan_requested)
    QTest.mouseClick(window.home._card_widgets["AIL303m"], Qt.LeftButton)
    wait_for(lambda: isinstance(window._dynamic_page, ModeScreen))
    QTest.mouseClick(window._dynamic_page.mode_cards["flash"], Qt.LeftButton)
    wait_for(lambda: isinstance(window._dynamic_page, FlashcardScreen) and not window._transition_in_progress)
    try:
        yield app, window, state, database
    finally:
        window.close()
        window.thread_pool.waitForDone(5000)
        window.deleteLater()
        app.processEvents()
        database.close()
        app.setStyle(previous_style)
        ThemeManager(app).apply("light")


@pytest.mark.parametrize("known", [True, False])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_mouse_rating_then_space_stays_in_flashcards(flash_window, known, theme):
    app, window, state, database = flash_window
    ThemeManager(app).apply(theme)
    screen = window._dynamic_page
    # First Space works inside the image, exactly as in the user's report.
    QTest.mouseClick(screen.viewer.viewport(), Qt.LeftButton)
    QTest.keyClick(app.focusWidget(), Qt.Key_Space)
    assert screen.viewer.answer_visible
    QTest.mouseClick(screen.known_button if known else screen.unknown_button, Qt.LeftButton)
    assert screen.service.position == state["initial_position"] + 1
    assert not screen.viewer.answer_visible
    # Deliver to the actual keyboard recipient, not forcibly to the page.
    QTest.keyClick(app.focusWidget(), Qt.Key_Space)
    app.processEvents()
    assert window.stack.currentWidget() is screen, "Space navigated away after a mouse rating"
    assert screen.viewer.answer_visible
    assert screen.service.session_id == state["session_id"]
    assert screen.service.order == state["order"]
    check_flash_profile(state, [known])
    active = database.active_flash_session("AIL303m")
    assert int(active["id"]) == state["session_id"]


def test_entering_flashcards_and_header_focus_keep_space_in_study(flash_window):
    app, window, state, _database = flash_window
    screen = window._dynamic_page
    assert app.focusWidget() is screen.viewer or screen.viewer.isAncestorOf(app.focusWidget())
    window.app_header.home_button.setFocus()
    assert app.focusWidget() is window.app_header.home_button
    QTest.keyClick(app.focusWidget(), Qt.Key_Space)
    assert window.stack.currentWidget() is screen
    assert screen.viewer.answer_visible
    QTest.keyClick(app.focusWidget(), Qt.Key_Space)
    assert not screen.viewer.answer_visible
    assert screen.isAncestorOf(app.focusWidget())
    check_flash_profile(state, [])


def test_hidden_flashcard_page_does_not_capture_other_buttons_space(flash_window):
    app, window, state, _database = flash_window
    screen = window._dynamic_page
    other = QWidget()
    layout = QVBoxLayout(other)
    button = QPushButton("Other page action")
    layout.addWidget(button)
    clicks = []
    button.clicked.connect(lambda: clicks.append(True))
    window.stack.addWidget(other)
    window.stack.setCurrentWidget(other)
    button.setFocus()
    app.processEvents()
    QTest.keyClick(app.focusWidget(), Qt.Key_Space)
    assert clicks == [True]
    assert not screen.viewer.answer_visible
    check_flash_profile(state, [])


def test_modal_text_field_space_is_not_intercepted_by_flashcards(flash_window):
    app, window, state, _database = flash_window
    screen = window._dynamic_page
    dialog = QDialog(window)
    dialog.setWindowModality(Qt.ApplicationModal)
    layout = QVBoxLayout(dialog)
    field = QLineEdit()
    layout.addWidget(field)
    try:
        dialog.show()
        dialog.activateWindow()
        field.setFocus()
        wait_for(lambda: app.focusWidget() is field)
        QTest.keyClick(app.focusWidget(), Qt.Key_Space)
        assert field.text() == " "
        assert not screen.viewer.answer_visible
        check_flash_profile(state, [])
    finally:
        dialog.close()
