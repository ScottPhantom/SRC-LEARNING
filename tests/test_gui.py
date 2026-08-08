from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QColor, QKeyEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from app.config import APP_NAME
from app.controllers.main_controller import MainWindow
from app.domain.models import (
    AppSettings,
    ExamConfig,
    FeedbackMode,
    Question,
    WeakQuestionReview,
)
from app.repositories.answer_key import AnswerKeyReport
from app.repositories.database import Database
from app.services.data_scanner import DataScannerService
from app.services.exam import ExamService
from app.services.study import CrammingService, FlashcardService
from app.ui import themes
from app.ui.answer_options import AnswerOptionsWidget
from app.ui.image_viewer import QuestionImageViewer
from app.ui.progress import SegmentedProgressBar
from app.ui.screens import (
    CrammingScreen,
    ExamConfigScreen,
    ExamScreen,
    FlashcardScreen,
    HistoryScreen,
    ModeScreen,
    ResultScreen,
    SettingsScreen,
)
from app.ui.themes import DARK_STYLE, LIGHT_STYLE, ThemeManager

QT_APP = QApplication.instance() or QApplication([])


def make_subject(root: Path, amount: int = 2):
    for index in range(amount):
        path = root / "DATA" / "GUI101" / "Selections_1_choose" / f"Câu {index}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1000, 500), "white").save(path)
    return DataScannerService(root / "DATA").scan()[0]


def test_question_viewer_crops_answer_band_and_never_restores_it(tmp_path: Path) -> None:
    subject = make_subject(tmp_path, 1)
    viewer = QuestionImageViewer()
    viewer.set_crop_region((0.0, 0.9, 0.25, 0.1))
    viewer.load_image(subject.questions[0].absolute_path)
    assert viewer.cropped_size == (1000, 450)
    assert viewer._pixmap_item.pixmap().height() == 450
    assert not hasattr(viewer, "_mask_item")
    assert not viewer.answer_visible
    viewer.reveal_answer()
    assert viewer.answer_visible
    assert viewer._pixmap_item.pixmap().height() == 450


def test_question_viewer_zoom_is_bounded_and_reset_fits(tmp_path: Path) -> None:
    subject = make_subject(tmp_path, 1)
    viewer = QuestionImageViewer()
    viewer.load_image(subject.questions[0].absolute_path)
    for _ in range(20):
        viewer.zoom_in()
    assert viewer.zoom_level == viewer._max_zoom
    for _ in range(30):
        viewer.zoom_out()
    assert viewer.zoom_level == viewer._min_zoom
    viewer.reset_zoom()
    assert viewer.zoom_level == 0
    assert viewer.toolbar.isVisibleTo(viewer)
    assert all(
        shortcut.context() == Qt.WindowShortcut
        for shortcut in viewer.zoom_in_shortcuts
    )
    assert viewer.zoom_out_shortcut.context() == Qt.WindowShortcut
    assert viewer.copy_shortcut.context() == Qt.WindowShortcut


def test_question_viewer_zoom_shortcuts_work_from_active_window(
    tmp_path: Path,
) -> None:
    subject = make_subject(tmp_path, 1)
    window = QWidget()
    viewer = QuestionImageViewer(window)
    outside_control = QPushButton("Điều khiển khác", window)
    outside_control.move(20, 20)
    viewer.resize(800, 500)
    viewer.load_image(subject.questions[0].absolute_path)
    window.resize(800, 500)
    window.show()
    viewer.show()
    outside_control.show()
    outside_control.raise_()
    outside_control.setFocus()
    QT_APP.processEvents()

    QTest.keyClick(outside_control, Qt.Key_Equal, Qt.ControlModifier)
    assert viewer.zoom_level == 1
    QTest.keyClick(outside_control, Qt.Key_Minus, Qt.ControlModifier)
    assert viewer.zoom_level == 0
    QTest.keyClick(outside_control, Qt.Key_Plus, Qt.ControlModifier)
    assert viewer.zoom_level == 1
    QT_APP.clipboard().clear()
    QTest.keyClick(outside_control, Qt.Key_C, Qt.ControlModifier)
    assert QT_APP.clipboard().pixmap().size() == viewer._pixmap_item.pixmap().size()
    window.close()


def test_zoom_toolbar_is_fixed_top_right_and_category_notice_toggles(
    tmp_path: Path,
) -> None:
    subject = make_subject(tmp_path, 1)
    viewer = QuestionImageViewer()
    viewer.resize(800, 500)
    viewer.load_image(
        subject.questions[0].absolute_path,
        category="Selections_Multiple_choose",
    )
    viewer.show()
    QT_APP.processEvents()
    initial_position = viewer.toolbar.pos()

    viewer.zoom_in()
    viewer.zoom_in()
    QT_APP.processEvents()

    assert viewer.toolbar.pos() == initial_position
    assert viewer.toolbar.x() + viewer.toolbar.width() <= viewer.width()
    assert [
        viewer.zoom_in_button.text(),
        viewer.reset_zoom_button.text(),
        viewer.zoom_out_button.text(),
        viewer.copy_image_button.text(),
    ] == ["+", "↻", "−", "📋"]
    assert not viewer.category_notice.isHidden()
    assert viewer.category_notice.text() == "Chú ý: Nhiều đáp án (Multiple_choose)"
    viewer.set_question_category("Selections_1_choose")
    assert viewer.category_notice.isHidden()
    viewer.close()


def test_viewer_copies_cropped_pixmap_and_shows_confirmation(tmp_path: Path) -> None:
    subject = make_subject(tmp_path, 1)
    viewer = QuestionImageViewer()
    viewer.resize(800, 500)
    assert not viewer.copy_image_button.isEnabled()
    assert not viewer.copy_image_to_clipboard()
    viewer.load_image(subject.questions[0].absolute_path)
    viewer.show()
    viewer.zoom_in()
    viewer.zoom_in()
    QT_APP.processEvents()
    QT_APP.clipboard().clear()

    assert viewer.copy_image_to_clipboard()

    copied = QT_APP.clipboard().pixmap()
    assert (copied.width(), copied.height()) == viewer.cropped_size == (1000, 450)
    assert viewer.copy_image_button.isEnabled()
    assert viewer.copy_image_button.toolTip() == "Sao chép ảnh vào Clipboard"
    assert not viewer.copy_toast.isHidden()
    assert viewer.copy_toast.text() == "Đã sao chép ảnh vào clipboard!"
    assert viewer._copy_toast_timer.isActive()
    assert viewer._copy_toast_timer.interval() == 1600

    QT_APP.clipboard().clear()
    viewer.setFocus()
    QTest.keyClick(viewer, Qt.Key_C, Qt.ControlModifier)
    QT_APP.processEvents()
    copied_with_shortcut = QT_APP.clipboard().pixmap()
    assert (copied_with_shortcut.width(), copied_with_shortcut.height()) == (1000, 450)
    viewer.close()


def test_exam_screen_preserves_answer_when_navigating(tmp_path: Path) -> None:
    subject = make_subject(tmp_path, 2)
    database = Database(tmp_path / "progress.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    answers = {question.relative_path: "A" for question in subject.questions}
    service = ExamService(database, subject.questions, answers)
    session = service.create_session(
        ExamConfig(
            subject=subject.name,
            categories=("Selections_1_choose",),
            question_count=2,
            duration_minutes=1,
            feedback_mode=FeedbackMode.DEFERRED,
        )
    )
    screen = ExamScreen(session, (0.0, 0.9, 0.25, 0.1))
    screen._option_widgets[0].setChecked(True)
    screen.go_to(1)
    assert session.items[0].selected_answer == "A"
    screen.go_to(0)
    assert screen._option_widgets[0].isChecked()
    screen._timer.stop()
    screen.deleteLater()
    database.close()


def test_immediate_exam_reveals_and_locks_after_confirmation(tmp_path: Path) -> None:
    subject = make_subject(tmp_path, 2)
    database = Database(tmp_path / "immediate.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    service = ExamService(
        database,
        subject.questions,
        {question.relative_path: "A" for question in subject.questions},
    )
    session = service.create_session(
        ExamConfig(
            subject=subject.name,
            categories=("Selections_1_choose",),
            question_count=2,
            duration_minutes=1,
            feedback_mode=FeedbackMode.IMMEDIATE,
        )
    )
    screen = ExamScreen(session, (0.0, 0.9, 0.25, 0.1))
    assert not screen.next.isEnabled()
    screen._option_widgets[0].setChecked(True)
    screen._confirm_current()
    assert session.current.confirmed
    assert screen.viewer.answer_visible
    assert screen.next.isEnabled()
    assert all(not widget.isEnabled() for widget in screen._option_widgets)
    assert screen.navigator.item(0).text() == "1"
    assert screen.navigator.state(0) == "correct"
    screen._timer.stop()
    screen.deleteLater()
    database.close()


def test_immediate_exam_marks_wrong_navigation_item_red(tmp_path: Path) -> None:
    subject = make_subject(tmp_path, 1)
    database = Database(tmp_path / "wrong-color.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    question = subject.questions[0]
    session = ExamService(
        database, subject.questions, {question.relative_path: "A"}
    ).create_session(
        ExamConfig(
            subject=subject.name,
            categories=("Selections_1_choose",),
            question_count=1,
            duration_minutes=1,
            feedback_mode=FeedbackMode.IMMEDIATE,
        )
    )
    screen = ExamScreen(session, (0.0, 0.9, 0.25, 0.1))
    screen._option_widgets[1].setChecked(True)
    screen._confirm_current()
    nav_item = screen.navigator.item(0)
    assert nav_item.text() == "1"
    assert screen.navigator.state(0) == "wrong"
    screen._timer.stop()
    screen.deleteLater()
    database.close()


def test_result_screen_retest_menu_exposes_both_navigation_choices(
    tmp_path: Path,
) -> None:
    subject = make_subject(tmp_path, 2)
    database = Database(tmp_path / "result-retest.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    config = ExamConfig(
        subject=subject.name,
        categories=("Selections_1_choose",),
        question_count=2,
        duration_minutes=40,
        feedback_mode=FeedbackMode.IMMEDIATE,
    )
    session = ExamService(
        database,
        subject.questions,
        {question.relative_path: "A" for question in subject.questions},
    ).create_session(config)
    result = session.submit()
    screen = ResultScreen(result, (0.0, 0.9, 0.25, 0.1))
    choices: list[str] = []
    screen.retest_requested.connect(choices.append)

    assert result.config == config
    assert screen.retest_button.text() == "↻ RE-Test"
    assert [action.text() for action in screen.retest_menu.actions()] == [
        "Làm lại với cấu hình cũ",
        "Tự chọn lại option mới",
    ]
    total_row = len(result.items)
    assert screen.table.columnCount() == 3
    assert screen.table.item(total_row, 1).text() == "FAIL"
    assert screen.table.item(total_row, 1).foreground().color() == QColor("#FF453A")
    screen.retest_same_action.trigger()
    screen.retest_new_action.trigger()
    assert choices == ["same_config", "new_config"]

    screen.deleteLater()
    database.close()


def test_result_table_has_total_pass_status_and_drives_image_review(
    tmp_path: Path,
) -> None:
    subject = make_subject(tmp_path, 2)
    database = Database(tmp_path / "result-table.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    session = ExamService(
        database,
        subject.questions,
        {question.relative_path: "A" for question in subject.questions},
    ).create_session(
        ExamConfig(
            subject=subject.name,
            categories=("Selections_1_choose",),
            question_count=2,
            duration_minutes=30,
            feedback_mode=FeedbackMode.DEFERRED,
        )
    )
    for index in range(2):
        session.current_index = index
        session.set_answer("A")
    result = session.submit()
    screen = ResultScreen(result, (0.0, 0.9, 0.25, 0.1))

    assert result.passed
    assert result.status == "PASS"
    assert screen.table.rowCount() == 3
    assert screen.table.columnCount() == 3
    assert [screen.table.horizontalHeaderItem(column).text() for column in range(3)] == [
        "NO",
        "Correct answer",
        "Điểm",
    ]
    assert screen.table.item(0, 0).text() == "Câu 1"
    assert screen.table.item(0, 1).text() == "A"
    assert screen.table.item(0, 1).foreground().color() == QColor("#30D158")
    assert screen.table.item(0, 2).text() == "5"
    assert screen.table.item(2, 0).text() == "Total"
    assert screen.table.item(2, 1).text() == "PASS"
    assert screen.table.item(2, 1).foreground().color() == QColor("#30D158")
    assert screen.table.item(2, 2).text() == "10.00 / 10"

    screen.table.setCurrentCell(1, 0)
    assert screen.viewer._path == result.items[1].question.absolute_path
    assert screen.viewer.answer_visible
    reviewed_path = screen.viewer._path
    screen.table.setCurrentCell(2, 0)
    assert screen.viewer._path == reviewed_path
    screen.deleteLater()
    database.close()


def test_exam_config_dynamically_clamps_count_to_filtered_pool(tmp_path: Path) -> None:
    data_dir = tmp_path / "DATA"
    subject_dir = data_dir / "DYNAMIC101"
    for category, amount in (("Selections_1_choose", 35), ("True_False", 7)):
        for index in range(amount):
            path = subject_dir / category / f"Câu {index}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (100, 60), "white").save(path)
    subject = DataScannerService(data_dir).scan()[0]
    answers = {question.relative_path: "A" for question in subject.questions}
    report = AnswerKeyReport(
        csv_path=subject.path / "answers.csv",
        file_found=True,
        total_rows=len(answers),
        answers=answers,
    )
    database = Database(tmp_path / "dynamic-count.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    screen = ExamConfigScreen(
        subject,
        ExamService(database, subject.questions, answers),
        report,
    )

    assert screen.max_available == 42
    assert screen.count_combo.currentText() == "30"
    assert screen.count_custom.maximum() == 42

    screen.category_boxes["Selections_1_choose"].setChecked(False)
    assert screen.max_available == 7
    assert screen.count_combo.currentText() == "Khác"
    assert screen.count_custom.value() == 7
    assert screen.count_custom.maximum() == 7
    assert "từ 30 xuống 7" in screen.count_warning.text()
    assert screen.start_button.isEnabled()

    screen.count_custom.lineEdit().textEdited.emit("99")
    assert screen.count_custom.value() == 7
    assert "Tối đa 7 câu" in screen.count_warning.text()

    screen.category_boxes["Selections_1_choose"].setChecked(True)
    screen.category_boxes["True_False"].setChecked(False)
    assert screen.max_available == 35
    screen.count_combo.setCurrentText("50")
    assert screen.count_combo.currentText() == "Khác"
    assert screen.count_custom.value() == 35
    assert screen.count_custom.maximum() == 35

    screen.category_boxes["Selections_1_choose"].setChecked(False)
    assert screen.max_available == 0
    assert screen.count_custom.value() == 0
    assert screen.count_custom.maximum() == 0
    assert not screen.start_button.isEnabled()
    screen.deleteLater()
    database.close()


def test_subject_view_cards_dashboard_and_quick_review(tmp_path: Path) -> None:
    subject = make_subject(tmp_path, 1)
    question = subject.questions[0]
    report = AnswerKeyReport(
        csv_path=subject.path / "answers.csv",
        file_found=True,
        total_rows=1,
        answers={question.relative_path: "B"},
    )
    review = WeakQuestionReview(
        question=question,
        correct_answer="B",
        total_attempts=5,
        wrong_count=4,
    )
    screen = ModeScreen(
        subject,
        report,
        {"known": 0, "learning": 1, "new": 0},
        {"Selections_1_choose": [review]},
        (0.0, 0.9, 0.25, 0.1),
    )
    screen.resize(1280, 800)
    screen.show()
    QT_APP.processEvents()

    assert set(screen.mode_cards) == {"flash", "cram", "exam"}
    assert all(
        card.minimumWidth() == card.minimumHeight() == 264
        for card in screen.mode_cards.values()
    )
    cards_container = screen.findChild(QWidget, "studyModeCardsContainer")
    assert cards_container is not None
    assert cards_container.height() == 337
    dashboard_top = screen.dashboard_tabs.geometry().top()
    assert not any(
        button.text() == "Bắt đầu" for button in screen.findChildren(QPushButton)
    )
    selected_modes: list[str] = []
    screen.mode_selected.connect(selected_modes.append)
    QTest.mouseClick(screen.mode_cards["flash"], Qt.LeftButton)
    assert selected_modes == ["flash"]

    assert screen.dashboard_tabs.count() == 4
    assert [
        screen.dashboard_tabs.tabText(index)
        for index in range(screen.dashboard_tabs.count())
    ] == ["Điền khuyết", "Chọn một", "Chọn nhiều", "Đúng/Sai"]
    table = screen.weak_tables["Selections_1_choose"]
    assert table.item(0, 0).text() == question.absolute_path.name
    assert table.item(0, 1).text() == "4 / 5"
    assert table.item(0, 2).text() == "80.0%"
    assert table.item(0, 2).foreground().color() == QColor("#FF453A")

    card = screen.mode_cards["flash"]
    other_cards = [
        screen.mode_cards[mode] for mode in ("cram", "exam")
    ]
    QApplication.sendEvent(card, QEvent(QEvent.Enter))
    QTest.qWait(280)
    assert card.property("hovered") is True
    assert card.minimumWidth() == card.minimumHeight() == 317
    assert card.shadow.blurRadius() >= 54
    assert screen.dashboard_tabs.geometry().top() == dashboard_top
    assert all(other.focus_overlay.isVisible() for other in other_cards)
    assert all(other.focus_overlay_effect.opacity() >= 0.49 for other in other_cards)
    QApplication.sendEvent(card, QEvent(QEvent.Leave))
    QTest.qWait(280)
    assert card.minimumWidth() == card.minimumHeight() == 264
    assert all(not other.focus_overlay.isVisible() for other in other_cards)

    table.cellDoubleClicked.emit(0, 0)
    QT_APP.processEvents()
    dialog = screen.quick_review_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.viewer._path == question.absolute_path
    assert dialog.viewer.cropped_size == (1000, 450)
    assert dialog.answer_label.text() == "B"
    dialog.close()
    screen.close()


def test_quick_review_opens_with_space_and_navigates_current_tab(
    tmp_path: Path,
) -> None:
    subject = make_subject(tmp_path, 3)
    reviews = [
        WeakQuestionReview(
            question=question,
            correct_answer=answer,
            total_attempts=index + 2,
            wrong_count=index + 1,
        )
        for index, (question, answer) in enumerate(
            zip(subject.questions, "ABC", strict=True)
        )
    ]
    report = AnswerKeyReport(
        csv_path=subject.path / "answers.csv",
        file_found=True,
        total_rows=3,
        answers={
            review.question.relative_path: review.correct_answer for review in reviews
        },
    )
    screen = ModeScreen(
        subject,
        report,
        {"known": 0, "learning": 0, "new": 3},
        {"Selections_1_choose": reviews},
        (0.0, 0.9, 0.25, 0.1),
    )
    screen.resize(1280, 800)
    screen.show()
    table = screen.weak_tables["Selections_1_choose"]
    screen.dashboard_tabs.setCurrentWidget(table)
    table.selectRow(1)
    table.setFocus()
    QT_APP.processEvents()

    QTest.keyClick(table, Qt.Key_Space)
    QT_APP.processEvents()
    dialog = screen.quick_review_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.current_index == 1
    assert dialog.viewer._path == reviews[1].question.absolute_path
    assert dialog.answer_label.text() == "B"
    assert "2/3" in dialog.windowTitle()

    dialog.viewer.setFocus()
    QTest.keyClick(dialog.viewer, Qt.Key_Right)
    assert dialog.current_index == 2
    assert dialog.answer_label.text() == "C"
    QTest.keyClick(dialog.viewer, Qt.Key_Right)
    assert dialog.current_index == 2
    QTest.keyClick(dialog.viewer, Qt.Key_Left)
    assert dialog.current_index == 1
    QTest.keyClick(dialog.viewer, Qt.Key_Left)
    QTest.keyClick(dialog.viewer, Qt.Key_Left)
    assert dialog.current_index == 0
    assert dialog.viewer._path == reviews[0].question.absolute_path

    QTest.keyClick(dialog.viewer, Qt.Key_Return)
    QT_APP.processEvents()
    assert not dialog.isVisible()
    screen.close()


def test_main_window_fades_between_subject_and_study_screens(tmp_path: Path) -> None:
    data_dir = tmp_path / "EMPTY_DATA"
    data_dir.mkdir()
    database = Database(tmp_path / "fade-transition.sqlite3")
    database.set_setting("data_dir", str(data_dir))
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    old_page = QWidget()
    new_page = QWidget()
    window._set_dynamic_page(old_page)

    window._set_dynamic_page(new_page, animate=True)

    assert window._transition_in_progress
    assert window._transition_group is not None
    assert window._transition_group.duration() == 300
    assert window.stack.currentWidget() is old_page
    QTest.qWait(180)
    assert window.stack.currentWidget() is new_page
    QTest.qWait(180)
    assert not window._transition_in_progress
    assert window._transition_group is None
    assert window.stack.count() == 2  # Home + màn hình mới.
    window.thread_pool.waitForDone(2000)
    window.deleteLater()
    database.close()


def test_theme_manager_resolves_system_to_detected_os_theme() -> None:
    manager = ThemeManager(QT_APP, system_detector=lambda: "Dark")

    assert manager.apply("system") == "dark"
    assert manager.selected_theme == "system"
    assert manager.applied_theme == "dark"
    assert QT_APP.styleSheet() == DARK_STYLE
    assert QT_APP.property("selectedTheme") == "system"
    assert QT_APP.property("appliedTheme") == "dark"

    manager.system_detector = lambda: "Light"
    assert manager.apply("system") == "light"
    assert QT_APP.styleSheet() == LIGHT_STYLE


def test_system_theme_falls_back_when_darkdetect_is_not_installed(
    monkeypatch,
) -> None:
    class CompletedProcess:
        returncode = 0
        stdout = "Dark\n"

    monkeypatch.setattr(themes, "_darkdetect", None)
    monkeypatch.setattr(themes.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        themes.subprocess,
        "run",
        lambda *_args, **_kwargs: CompletedProcess(),
    )

    assert themes.detect_system_theme() == "Dark"


def test_settings_combobox_emits_live_preview_without_persisting(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "theme-preview.sqlite3")
    database.set_setting("theme", "light")
    settings = AppSettings(theme="light", data_dir=str(tmp_path / "DATA"))
    screen = SettingsScreen(settings)
    requested: list[str] = []
    screen.theme_preview_requested.connect(requested.append)

    screen.theme.setCurrentIndex(screen.theme.findData("dark"))

    assert requested == ["dark"]
    assert database.get_setting("theme") == "light"
    assert "tự dò" in screen.theme.toolTip()
    screen.deleteLater()
    database.close()


def test_controller_live_previews_then_persists_theme_only_on_save(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "EMPTY_DATA"
    data_dir.mkdir()
    database = Database(tmp_path / "theme-controller.sqlite3")
    database.set_setting("data_dir", str(data_dir))
    database.set_setting("theme", "light")
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    window.show_settings()
    page = window._dynamic_page

    page.theme.setCurrentIndex(page.theme.findData("dark"))
    assert window.theme_manager.applied_theme == "dark"
    assert QT_APP.styleSheet() == DARK_STYLE
    assert database.get_setting("theme") == "light"

    monkeypatch.setattr(
        "app.controllers.main_controller.QMessageBox.information",
        lambda *_args: None,
    )
    page._save()
    assert database.get_setting("theme") == "dark"
    assert window.settings.theme == "dark"
    window.thread_pool.waitForDone(2000)
    window.deleteLater()
    ThemeManager(QT_APP, system_detector=lambda: "Light").apply("light")
    database.close()


def test_flashcard_progress_increments_after_rating(tmp_path: Path) -> None:
    subject = make_subject(tmp_path, 3)
    database = Database(tmp_path / "flash-progress.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    screen = FlashcardScreen(
        FlashcardService(database, subject.questions), (0.0, 0.9, 0.25, 0.1)
    )
    assert screen.session_progress.maximum() == 3
    assert screen.session_progress.value() == 0
    assert not screen.session_progress.isTextVisible()
    screen.viewer.reveal_answer()
    screen._rate(True)
    assert screen.session_progress.value() == 1
    screen.deleteLater()
    database.close()


def test_flashcard_answer_panel_reads_answer_key_and_clears_on_next(
    tmp_path: Path,
) -> None:
    subject = make_subject(tmp_path, 2)
    database = Database(tmp_path / "flash-answer-panel.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    answers = {question.relative_path: "B" for question in subject.questions}
    screen = FlashcardScreen(
        FlashcardService(database, subject.questions, answers),
        (0.0, 0.9, 0.25, 0.1),
    )
    screen.show()
    QT_APP.processEvents()
    assert screen.answer_label.isHidden()
    QTest.keyClick(screen, Qt.Key_Space)
    assert screen.answer_label.text() == "B"
    assert not screen.answer_label.isHidden()
    assert screen.known_button.isEnabled()
    QTest.keyClick(screen, Qt.Key_Space)
    assert screen.answer_label.isHidden()
    assert not screen.known_button.isEnabled()
    QTest.keyClick(screen, Qt.Key_Space)
    screen._rate(True)
    assert screen.answer_label.isHidden()
    assert screen.viewer.cropped_size == (1000, 450)
    screen.deleteLater()
    database.close()


def test_flashcard_completion_automatically_starts_a_new_session(
    tmp_path: Path, monkeypatch
) -> None:
    subject = make_subject(tmp_path, 1)
    database = Database(tmp_path / "flash-auto-reset.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    answers = {subject.questions[0].relative_path: "A"}
    messages: list[str] = []
    monkeypatch.setattr(
        "app.ui.screens.QMessageBox.information",
        lambda _parent, _title, message: messages.append(message),
    )
    screen = FlashcardScreen(
        FlashcardService(database, subject.questions, answers),
        (0.0, 0.9, 0.25, 0.1),
    )
    first_session_id = screen.service.session_id

    screen.viewer.reveal_answer()
    screen._rate(True)

    state = screen.service.state()
    assert messages == ["Bạn đã hoàn thành phiên Flashcard!"]
    assert screen.new_button.text() == "Học lại"
    assert screen.service.session_id != first_session_id
    assert state.position == 0
    assert not state.completed
    assert screen.session_progress.value() == 0
    screen.deleteLater()
    database.close()


def test_flashcard_arrow_navigation_skips_and_opens_read_only_history(
    tmp_path: Path,
) -> None:
    subject = make_subject(tmp_path, 3)
    database = Database(tmp_path / "flash-history.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    screen = FlashcardScreen(
        FlashcardService(database, subject.questions), (0.0, 0.9, 0.25, 0.1)
    )
    screen._next_question()
    assert screen.session_progress.value() == 1
    assert len(screen.history_stack) == 1
    assert not screen.history_stack[0].known
    screen._previous_question()
    assert screen._history_cursor == 0
    assert screen.viewer.answer_visible
    assert not screen.known_button.isEnabled()
    assert "Chỉ xem" in screen.history_notice.text()
    screen._next_question()
    assert screen._history_cursor is None
    assert not screen.viewer.answer_visible
    screen.deleteLater()
    database.close()


def test_cramming_enter_grades_queue_and_history_is_read_only(tmp_path: Path) -> None:
    subject = make_subject(tmp_path, 3)
    database = Database(tmp_path / "cram-input.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    answers = {question.relative_path: "A" for question in subject.questions}
    screen = CrammingScreen(
        CrammingService(database, subject.questions, answers), (0.0, 0.9, 0.25, 0.1)
    )
    assert screen.sidebar.sizePolicy().horizontalPolicy() == QSizePolicy.Fixed
    assert screen.viewer.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    first_id = screen._live_state.question.id
    screen.answer_options.option_widgets[0].setChecked(True)
    screen._submit_answer()
    assert screen._awaiting_navigation
    assert screen._live_state.question.id == first_id
    assert screen.answer_options.option_widgets[0].property("answerState") == "correct"
    assert screen.viewer.answer_visible
    assert screen.service.state().question.id != first_id
    first_stat = database.question_error_stats([first_id])[first_id]
    assert (first_stat.total_attempts, first_stat.wrong_count) == (1, 0)
    screen._submit_answer()
    repeated_stat = database.question_error_stats([first_id])[first_id]
    assert repeated_stat.total_attempts == 1

    # Enter only grades; Right explicitly advances to the already-persisted queue head.
    screen._next_question()
    assert not screen._awaiting_navigation
    assert screen.round_progress.bars[0].value() == 1
    assert screen.round_progress.bars[0].maximum() == 3

    # A wrong choice is red, while the canonical answer is green.
    second_id = screen._live_state.question.id
    screen.answer_options.option_widgets[1].setChecked(True)
    screen._submit_answer()
    states = {
        widget.text(): widget.property("answerState")
        for widget in screen.answer_options.option_widgets
    }
    assert states["A"] == "correct"
    assert states["B"] == "wrong"
    assert screen._awaiting_navigation
    assert screen.service.state().wrong == 1
    second_stat = database.question_error_stats([second_id])[second_id]
    assert (second_stat.total_attempts, second_stat.wrong_count) == (1, 1)

    # Left skips the result currently on screen and opens the actual previous entry.
    screen._previous_question()
    assert screen._history_cursor == len(screen.history_stack) - 2
    assert all(not widget.isEnabled() for widget in screen.answer_options.option_widgets)
    assert "Chỉ xem" in screen.history_notice.text()
    screen._next_question()
    assert screen._history_cursor == len(screen.history_stack) - 1
    screen._next_question()
    assert screen._history_cursor is None
    assert not screen._awaiting_navigation
    screen.deleteLater()
    database.close()


def test_main_window_default_and_minimum_sizes(tmp_path: Path) -> None:
    data_dir = tmp_path / "EMPTY_DATA"
    data_dir.mkdir()
    database = Database(tmp_path / "window-size.sqlite3")
    database.set_setting("data_dir", str(data_dir))
    window = MainWindow(database)

    assert (window.width(), window.height()) == (1280, 800)
    assert (window.minimumWidth(), window.minimumHeight()) == (1100, 700)
    assert window.windowTitle() == APP_NAME == "SRC LEARNING"
    assert window.app_header.title_label.text() == "SRC Learning"
    assert window.app_header.home_button.isFlat()

    window.thread_pool.waitForDone(2000)
    window.deleteLater()
    database.close()


def test_global_home_handles_cancel_discard_and_submit_active_exam(
    tmp_path: Path, monkeypatch
) -> None:
    subject = make_subject(tmp_path, 3)
    database = Database(tmp_path / "home-exam-exit.sqlite3")
    database.set_setting("data_dir", str(tmp_path / "DATA"))
    database.sync_questions(subject.questions, [subject.name])
    answers = {question.relative_path: "A" for question in subject.questions}
    config = ExamConfig(
        subject=subject.name,
        categories=("Selections_1_choose",),
        question_count=2,
        duration_minutes=30,
        feedback_mode=FeedbackMode.DEFERRED,
    )
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    monkeypatch.setattr(window, "refresh_data", lambda: None)
    captured_dialog: dict[str, object] = {}

    def capture_exit_dialog(dialog: QMessageBox) -> int:
        captured_dialog["text"] = dialog.text()
        captured_dialog["buttons"] = {button.text() for button in dialog.buttons()}
        return 0

    monkeypatch.setattr(QMessageBox, "exec_", capture_exit_dialog)
    assert window._ask_active_exam_exit() == "cancel"
    assert captured_dialog["text"] == (
        "Bài thi đang làm sẽ không được lưu. Bạn muốn xử lý thế nào?"
    )
    assert captured_dialog["buttons"] == {
        "Cancel",
        "Yes — Nộp và Thoát",
        "No — Thoát và Không lưu",
    }
    window.current_subject = subject
    first_session = ExamService(database, subject.questions, answers).create_session(config)
    window.start_exam(first_session)
    exam_page = window.active_exam_screen
    assert exam_page is not None and exam_page.active

    monkeypatch.setattr(window, "_ask_active_exam_exit", lambda: "cancel")
    QTest.mouseClick(window.app_header.home_button, Qt.LeftButton)
    assert window.stack.currentWidget() is exam_page
    assert window.active_exam_screen is exam_page
    assert exam_page._timer.isActive()
    assert not database.exam_history()

    monkeypatch.setattr(window, "_ask_active_exam_exit", lambda: "discard")
    QTest.mouseClick(window.app_header.home_button, Qt.LeftButton)
    assert window.stack.currentWidget() is window.home
    assert window.active_exam_screen is None
    assert window.current_subject is None
    assert not first_session.submitted
    assert not database.exam_history()

    window.current_subject = subject
    second_session = ExamService(database, subject.questions, answers).create_session(config)
    second_session.set_answer("A")
    window.start_exam(second_session)
    monkeypatch.setattr(window, "_ask_active_exam_exit", lambda: "submit")
    QTest.mouseClick(window.app_header.home_button, Qt.LeftButton)
    assert window.stack.currentWidget() is window.home
    assert second_session.submitted
    history = database.exam_history()
    assert len(history) == 1
    assert history[0]["submit_reason"] == "exit"

    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    window.close()
    database.close()


def test_history_screen_multi_selection_and_controller_delete_refresh(
    tmp_path: Path, monkeypatch
) -> None:
    subject = make_subject(tmp_path, 3)
    database = Database(tmp_path / "delete-history.sqlite3")
    database.set_setting("data_dir", str(tmp_path / "DATA"))
    database.sync_questions(subject.questions, [subject.name])
    answers = {question.relative_path: "A" for question in subject.questions}
    service = ExamService(database, subject.questions, answers)
    config = ExamConfig(
        subject=subject.name,
        categories=("Selections_1_choose",),
        question_count=2,
        duration_minutes=30,
        feedback_mode=FeedbackMode.DEFERRED,
    )
    attempt_ids = [service.create_session(config).submit().attempt_id for _ in range(2)]
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    window.show_history()
    page = window._dynamic_page
    assert isinstance(page, HistoryScreen)
    assert not page.delete_button.isEnabled()
    assert page.tree.selectionMode() == QAbstractItemView.ExtendedSelection
    subject_node = page.tree.topLevelItem(0)
    assert subject_node.text(0) == f"📁 Môn học: {subject.name}"
    assert not subject_node.flags() & Qt.ItemIsSelectable
    assert subject_node.childCount() == 2
    subject_node.setSelected(True)
    QT_APP.processEvents()
    assert not page.delete_button.isEnabled()
    subject_node.child(0).setSelected(True)
    subject_node.child(1).setSelected(True)
    QT_APP.processEvents()
    assert page.delete_button.isEnabled()
    assert page.selected_attempt_ids() == sorted(attempt_ids)

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Cancel)
    QTest.mouseClick(page.delete_button, Qt.LeftButton)
    assert len(database.exam_history()) == 2

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    QTest.mouseClick(page.delete_button, Qt.LeftButton)
    refreshed = window._dynamic_page
    assert isinstance(refreshed, HistoryScreen)
    assert refreshed is not page
    assert not refreshed.delete_button.isEnabled()
    assert not database.exam_history()
    assert all(not database.exam_detail(attempt_id) for attempt_id in attempt_ids)

    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    window.close()
    database.close()


def test_controller_retest_reuses_exact_config_or_returns_to_config(
    tmp_path: Path, monkeypatch
) -> None:
    subject = make_subject(tmp_path, 3)
    database = Database(tmp_path / "controller-retest.sqlite3")
    database.set_setting("data_dir", str(tmp_path / "DATA"))
    database.sync_questions(subject.questions, [subject.name])
    config = ExamConfig(
        subject=subject.name,
        categories=("Selections_1_choose",),
        question_count=2,
        duration_minutes=50,
        feedback_mode=FeedbackMode.DEFERRED,
    )
    exam_service = ExamService(
        database,
        subject.questions,
        {question.relative_path: "A" for question in subject.questions},
    )
    result = exam_service.create_session(config).submit()
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    window.subjects = {subject.name: subject}
    window.current_subject = subject
    received_configs: list[ExamConfig] = []
    started_sessions: list[object] = []
    config_routes: list[bool] = []
    sentinel_session = object()

    class RetestService:
        def create_session(self, received: ExamConfig):
            received_configs.append(received)
            return sentinel_session

    monkeypatch.setattr(window, "_exam_service", lambda: RetestService())
    monkeypatch.setattr(window, "start_exam", started_sessions.append)
    monkeypatch.setattr(window, "show_exam_config", lambda: config_routes.append(True))

    window.show_result(result)
    result_page = window._dynamic_page
    result_page.retest_same_action.trigger()
    result_page.retest_new_action.trigger()

    assert received_configs == [config]
    assert started_sessions == [sentinel_session]
    assert config_routes == [True]
    assert window.current_subject is subject
    window.deleteLater()
    database.close()


def test_cramming_right_arrow_requires_enter_and_does_not_mutate_queue(tmp_path: Path) -> None:
    subject = make_subject(tmp_path, 2)
    database = Database(tmp_path / "cram-skip.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    answers = {question.relative_path: "A" for question in subject.questions}
    screen = CrammingScreen(
        CrammingService(database, subject.questions, answers), (0.0, 0.9, 0.25, 0.1)
    )
    before = screen.service.state()
    screen._next_question()
    after = screen.service.state()
    assert after.question.id == before.question.id
    assert after.wrong == before.wrong == 0
    assert after.round_mastered == before.round_mastered == 0
    assert not screen.history_stack
    assert not screen._awaiting_navigation
    assert "nhấn Enter" in screen.feedback.text()
    stat = database.question_error_stats([before.question.id])[before.question.id]
    assert (stat.total_attempts, stat.wrong_count) == (0, 0)
    screen.deleteLater()
    database.close()


def test_segmented_progress_represents_completed_current_and_future_rounds() -> None:
    widget = SegmentedProgressBar()
    widget.set_progress(
        total_rounds=4,
        current_round=2,
        round_mastered=3,
        round_total=10,
    )
    assert len(widget.bars) == 4
    assert [bar.property("segmentState") for bar in widget.bars] == [
        "completed",
        "current",
        "future",
        "future",
    ]
    assert [(bar.value(), bar.maximum()) for bar in widget.bars] == [
        (1, 1),
        (3, 10),
        (0, 1),
        (0, 1),
    ]
    assert all(not bar.isTextVisible() for bar in widget.bars)
    widget.set_progress(
        total_rounds=4,
        current_round=4,
        round_mastered=10,
        round_total=10,
        completed=True,
    )
    assert all(bar.value() == bar.maximum() for bar in widget.bars)
    widget.deleteLater()


def test_shared_answer_options_uses_checkboxes_for_multiple_choice(
    tmp_path: Path,
) -> None:
    path = (
        tmp_path
        / "DATA"
        / "GUI101"
        / "Selections_Multiple_choose"
        / "Câu nhiều.png"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1000, 500), "white").save(path)
    question = DataScannerService(tmp_path / "DATA").scan()[0].questions[0]
    widget = AnswerOptionsWidget()
    widget.set_question(question)
    widget.option_widgets[0].setChecked(True)
    widget.option_widgets[2].setChecked(True)
    assert widget.selected_answer() == "AC"
    widget.show_feedback(question, "AC", "ABC")
    assert all(not option.isEnabled() for option in widget.option_widgets)
    assert widget.option_widgets[0].property("answerState") == "correct"
    assert widget.option_widgets[1].property("answerState") == "correct"
    widget.deleteLater()


def test_answer_grid_supports_a_to_h_hints_and_multiple_toggle(tmp_path: Path) -> None:
    question = Question(
        id="eight-options",
        subject="GUI101",
        category="Selections_Multiple_choose",
        relative_path="Selections_Multiple_choose/Câu 8 lựa chọn.png",
        absolute_path=tmp_path / "Câu 8 lựa chọn.png",
        correct_answer="AH",
        option_letters=tuple("ABCDEFGH"),
    )
    widget = AnswerOptionsWidget()
    widget.set_question(question)

    assert [button.text() for button in widget.option_widgets] == list("ABCDEFGH")
    assert [button.shortcut_hint.text() for button in widget.option_widgets] == list(
        "12345678"
    )
    assert widget.toggle_option("A")
    assert widget.toggle_option("B")
    assert widget.selected_answer() == "AB"
    widget.toggle_option("A")
    assert widget.selected_answer() == "B"
    widget.deleteLater()


def test_exam_keymap_toggles_single_choice_and_grid_navigates(tmp_path: Path) -> None:
    subject = make_subject(tmp_path, 3)
    database = Database(tmp_path / "exam-keymap.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    answers = {question.relative_path: "A" for question in subject.questions}
    session = ExamService(database, subject.questions, answers).create_session(
        ExamConfig(
            subject=subject.name,
            categories=("Selections_1_choose",),
            question_count=3,
            duration_minutes=1,
            feedback_mode=FeedbackMode.DEFERRED,
        )
    )
    screen = ExamScreen(session, (0.0, 0.9, 0.25, 0.1))

    screen.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_1, Qt.NoModifier))
    assert session.current.selected_answer == "A"
    assert screen.navigator.state(0) == "answered"
    assert screen.navigator.summary.text() == "Câu hỏi (1 / 3)"

    screen.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_B, Qt.NoModifier))
    assert session.current.selected_answer == "B"
    screen.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_B, Qt.NoModifier))
    assert session.current.selected_answer == ""

    screen.navigator.buttons[2].click()
    assert session.current_index == 2
    assert screen.navigator.buttons[2].property("current") is True
    screen._timer.stop()
    screen.deleteLater()
    database.close()


def test_cramming_grid_click_focuses_unmastered_queue_item(tmp_path: Path) -> None:
    subject = make_subject(tmp_path, 3)
    database = Database(tmp_path / "cram-grid.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    answers = {question.relative_path: "A" for question in subject.questions}
    screen = CrammingScreen(
        CrammingService(database, subject.questions, answers),
        (0.0, 0.9, 0.25, 0.1),
    )
    items = screen.service.current_round_items()
    current_id = screen.service.state().question.id
    target_index = next(
        index for index, item in enumerate(items) if item.question.id != current_id
    )
    target_id = items[target_index].question.id

    screen.navigator.buttons[target_index].click()

    assert screen.service.state().question.id == target_id
    assert screen.navigator.buttons[target_index].property("current") is True
    assert screen.navigator.summary.text() == "Câu hỏi (0 / 3)"
    screen.deleteLater()
    database.close()


def test_home_screen_loading_and_subjects_states(tmp_path: Path) -> None:
    from app.ui.screens import HomeScreen
    from app.ui.subject_card import SubjectCard, extract_monogram

    assert extract_monogram("ITE303c") == "ITE"
    assert extract_monogram("MAS291") == "MAS"
    assert extract_monogram("MAI391") == "MAI"
    assert extract_monogram("ADY201m") == "ADY"
    assert extract_monogram("PRJ301") == "PRJ"
    assert extract_monogram("CS101") == "CS"
    assert extract_monogram("X1") == "X"
    assert extract_monogram("123") == "SUB"

    home = HomeScreen()
    data_dir = tmp_path / "DATA"
    data_dir.mkdir()

    # Test set_loading không crash
    home.set_loading(data_dir)
    assert "Đang quét" in home.status_capsule.label.text()

    # Test set_subjects với 0 môn
    home.set_subjects([], data_dir)
    assert home.cards_grid.count() == 0
    assert "Chưa có môn học" in home.status_capsule.label.text()

    # Test set_subjects với 1 môn
    subject1 = make_subject(tmp_path, 2)
    home.set_subjects([subject1], data_dir)
    assert home.cards_grid.count() == 1
    card1 = home.cards_grid.itemAt(0).widget()
    assert isinstance(card1, SubjectCard)
    assert card1.title_label.text() == subject1.name
    assert f"{subject1.question_count} câu hỏi" in card1.count_label.text()
    assert "Multiple_choose" not in card1.title_label.text()

    # Test set_subjects với 3 môn
    subject2 = make_subject(tmp_path, 1)
    subject2.name = "CS101"
    subject3 = make_subject(tmp_path, 4)
    subject3.name = "PHY202"
    home.set_subjects([subject1, subject2, subject3], data_dir)
    assert home.cards_grid.count() == 3
    assert "3 môn học" in home.status_capsule.label.text()
    home.deleteLater()


def test_subject_card_click_and_keyboard_signals(tmp_path: Path) -> None:
    from app.ui.subject_card import SubjectCard
    subject = make_subject(tmp_path, 2)
    card = SubjectCard(subject)
    card.show()
    card.setFocus()
    emitted = []
    card.selected.connect(lambda name: emitted.append(name))

    # Click test
    QTest.mouseClick(card, Qt.LeftButton)
    assert emitted == [subject.name]

    # Enter key test
    QTest.keyClick(card, Qt.Key_Return)
    assert emitted == [subject.name, subject.name]

    # Space key test
    card.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier))
    assert emitted == [subject.name, subject.name, subject.name]
    card.deleteLater()


def test_app_header_actions_and_mode_toggle() -> None:
    from PyQt5.QtWidgets import QVBoxLayout, QWidget

    from app.ui.screens import AppHeader
    win = QWidget()
    win.resize(600, 100)
    layout = QVBoxLayout(win)
    header = AppHeader()
    layout.addWidget(header)
    win.show()
    QT_APP.processEvents()

    history_calls = []
    refresh_calls = []
    settings_calls = []

    header.history_requested.connect(lambda: history_calls.append(True))
    header.refresh_requested.connect(lambda: refresh_calls.append(True))
    header.settings_requested.connect(lambda: settings_calls.append(True))

    header.history_button.click()
    header.refresh_button.click()
    header.settings_button.click()

    assert len(history_calls) == 1
    assert len(refresh_calls) == 1
    assert len(settings_calls) == 1

    animated = header.refresh_button
    QApplication.sendEvent(animated, QEvent(QEvent.Enter))
    assert animated._hover_animation is not None
    assert animated._hover_animation.duration() == 200
    QTest.qWait(230)
    assert animated.minimumSize() == animated.HOVER_SIZE
    assert animated.maximumSize() == animated.HOVER_SIZE
    assert animated.shadow.blurRadius() >= 21
    assert animated.hoverBackground.alpha() > 0
    QApplication.sendEvent(animated, QEvent(QEvent.Leave))
    QTest.qWait(230)
    assert animated.minimumSize() == animated.BASE_SIZE
    assert animated.maximumSize() == animated.BASE_SIZE
    assert animated.shadow.color().alpha() == 0

    header.set_home_mode(False)
    assert not header.action_capsule.isVisible()

    header.set_home_mode(True)
    assert header.action_capsule.isVisible()
    win.close()
    win.deleteLater()


def test_history_tree_groups_subjects_formats_local_time_and_selects_only_exams() -> None:
    from app.ui.screens import HistoryScreen

    history = [
        {
            "id": 24,
            "subject": "ITE303c",
            "score": 8.5,
            "score_percent": 85.0,
            "submitted_at": "2026-08-07T07:30:39+00:00",
        },
        {
            "id": 23,
            "subject": "ITE303c",
            "score": 7.0,
            "score_percent": 70.0,
            "submitted_at": "2026-08-06T01:15:00Z",
        },
        {
            "id": 8,
            "subject": "MATH101",
            "score": 6.0,
            "score_percent": 60.0,
            "submitted_at": "invalid-time",
        },
    ]
    screen = HistoryScreen(history)
    screen.show()
    QT_APP.processEvents()

    assert screen.tree.topLevelItemCount() == 2
    first_subject = screen.tree.topLevelItem(0)
    assert first_subject.text(0) == "📁 Môn học: ITE303c"
    assert first_subject.font(0).bold()
    assert first_subject.background(0).color() == QColor("#D8DCE3")
    assert first_subject.childCount() == 2
    assert first_subject.child(0).text(0) == "Bài thi #24"
    assert "ITE303c" not in first_subject.child(0).text(0)
    assert first_subject.child(0).text(2) == HistoryScreen._format_submitted_at(
        history[0]["submitted_at"]
    )
    assert first_subject.child(0).text(2).count(":") == 1
    assert first_subject.child(0).text(2).count("/") == 2
    second_subject = screen.tree.topLevelItem(1)
    assert second_subject.text(0) == "📁 Môn học: MATH101"
    assert second_subject.child(0).text(2) == "invalid-time"

    first_subject.setSelected(True)
    assert not screen.delete_button.isEnabled()
    first_subject.child(0).setSelected(True)
    QT_APP.processEvents()
    assert screen.delete_button.isEnabled()
    assert screen.selected_attempt_ids() == [24]
    screen.close()


def test_theme_switch_applies_and_repaints(tmp_path: Path) -> None:
    from app.ui.screens import HomeScreen
    from app.ui.themes import ThemeManager

    subject = make_subject(tmp_path, 2)
    home = HomeScreen()
    home.set_subjects([subject], tmp_path / "DATA")

    manager = ThemeManager(QT_APP)
    manager.apply("dark")
    assert QT_APP.property("appliedTheme") == "dark"
    home.repaint()

    manager.apply("light")
    assert QT_APP.property("appliedTheme") == "light"
    home.repaint()
    home.deleteLater()


def test_home_grid_reflow_preserves_card_instances(tmp_path: Path) -> None:
    from app.ui.screens import HomeScreen
    subject1 = make_subject(tmp_path, 2)
    subject1.name = "MATH"
    subject2 = make_subject(tmp_path, 3)
    subject2.name = "PHYSICS"

    home = HomeScreen()
    home.set_subjects([subject1, subject2], tmp_path / "DATA")
    card1_before = home._card_widgets["MATH"]
    card2_before = home._card_widgets["PHYSICS"]
    card1_id = id(card1_before)
    card2_id = id(card2_before)

    # Trigger resize reflow
    home.resize(700, 800)
    home._reflow_grid(force=True)
    QT_APP.processEvents()

    card1_after = home._card_widgets["MATH"]
    card2_after = home._card_widgets["PHYSICS"]

    assert id(card1_after) == card1_id
    assert id(card2_after) == card2_id
    assert home.cards_grid.alignment() & Qt.AlignLeft
    assert home.cards_grid.alignment() & Qt.AlignTop
    home.deleteLater()


def test_toolbar_icon_size_alignment_and_reload_pixels() -> None:
    from PyQt5.QtCore import QSize
    from PyQt5.QtGui import QColor

    from app.ui.icons import create_line_icon
    from app.ui.screens import AppHeader

    header = AppHeader()

    for btn in (header.history_button, header.refresh_button, header.settings_button):
        assert btn.iconSize() == QSize(24, 24)
        assert btn.minimumWidth() == 36
        assert btn.minimumHeight() == 36

    # Kiểm tra icon refresh có pixel ở cả 4 góc phần tư
    icon = create_line_icon("refresh", size=24, color=QColor("#0A84FF"))
    pixmap = icon.pixmap(24, 24)
    image = pixmap.toImage()

    # Kiểm tra 4 góc phần tư có ít nhất 1 pixel không trong suốt
    w, h = image.width(), image.height()
    quad1 = any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(w // 2)
        for y in range(h // 2)
    )
    quad2 = any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(w // 2, w)
        for y in range(h // 2)
    )
    quad3 = any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(w // 2)
        for y in range(h // 2, h)
    )
    quad4 = any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(w // 2, w)
        for y in range(h // 2, h)
    )

    assert quad1 and quad2 and quad3 and quad4, "Reload icon phải vẽ dạng vòng tròn phủ cả 4 góc phần tư"
    header.deleteLater()


def test_settings_image_viewer_dynamic_path_and_placeholder(tmp_path: Path) -> None:
    from app.controllers import MainWindow
    from app.domain.models import AppSettings
    from app.repositories.database import Database
    from app.ui.screens import SettingsScreen

    # 1. Test với preview_path = None -> placeholder_frame hiển thị
    settings = AppSettings()
    screen_none = SettingsScreen(settings, preview_path=None)
    assert screen_none.placeholder_frame is not None
    assert screen_none.preview is None

    # 2. Test với đường dẫn file không tồn tại -> placeholder_frame hiển thị
    fake_path = tmp_path / "non_existent.png"
    screen_fake = SettingsScreen(settings, preview_path=fake_path)
    assert screen_fake.placeholder_frame is not None
    assert screen_fake.preview is None

    # 3. Test với file ảnh thật từ make_subject
    subject = make_subject(tmp_path, 2)
    img_path = subject.questions[0].absolute_path

    screen_real = SettingsScreen(settings, preview_path=img_path)
    assert screen_real.preview is not None
    assert screen_real.placeholder_frame is None

    # 4. Test thay đổi Crop Spinbox -> cập nhật preview
    screen_real.crop_values[1].setValue(20.0)  # Crop Y = 20%
    QT_APP.processEvents()

    # 5. Test MainWindow show_settings() chọn ảnh động từ Controller
    db = Database(tmp_path / "test.sqlite3")
    window = MainWindow(db)
    window.data_dir = tmp_path / "DATA"
    window.subjects = {subject.name: subject}
    window.show_settings()

    dynamic_page = window._dynamic_page
    assert isinstance(dynamic_page, SettingsScreen)
    assert dynamic_page.preview is not None

    screen_none.deleteLater()
    screen_fake.deleteLater()
    screen_real.deleteLater()
    window.thread_pool.waitForDone(2000)
    window.close()
    window.deleteLater()
    db.close()


def test_light_home_background_asset_and_variant_rendering() -> None:
    from PyQt5.QtCore import QRectF
    from PyQt5.QtGui import QImage, QPainter

    import app.ui.background as bg_mod
    from app.ui.background import (
        LIGHT_HOME_BG_ASSET,
        get_home_light_pixmap,
        paint_app_background,
        resolve_resource_path,
    )
    from app.ui.screens import BasePage, HomeBackgroundCanvas
    from app.ui.themes import ThemeManager

    # 1. Test resource resolver
    resolved = resolve_resource_path(LIGHT_HOME_BG_ASSET)
    assert resolved.exists(), f"Asset {LIGHT_HOME_BG_ASSET} phải tồn tại ở {resolved}"

    # 2. Test QPixmap load asset thành công
    pixmap = get_home_light_pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert pixmap.width() > 0 and pixmap.height() > 0

    # 3. Test HomeBackgroundCanvas dùng variant='home'
    canvas = HomeBackgroundCanvas()
    assert canvas.variant == "home"

    # Test BasePage canvas
    page = BasePage()

    # 4. Test paint_app_background không throw ở cả Light và Dark mode với các variant
    manager = ThemeManager(QT_APP)
    img = QImage(800, 600, QImage.Format_ARGB32)

    # Light Mode
    manager.apply("light")
    painter = QPainter(img)
    paint_app_background(painter, QRectF(0, 0, 800, 600), dark=False, variant="home")
    paint_app_background(painter, QRectF(0, 0, 800, 600), dark=False, variant="default")
    painter.end()

    # Dark Mode
    manager.apply("dark")
    painter = QPainter(img)
    paint_app_background(painter, QRectF(0, 0, 800, 600), dark=True, variant="home")
    paint_app_background(painter, QRectF(0, 0, 800, 600), dark=True, variant="default")
    painter.end()

    # 5. Test fallback khi missing asset
    orig_pixmap = bg_mod._HOME_LIGHT_PIXMAP
    orig_loaded = bg_mod._HOME_LIGHT_LOADED
    try:
        bg_mod._HOME_LIGHT_PIXMAP = None
        bg_mod._HOME_LIGHT_LOADED = True  # Giả lập không có pixmap
        painter = QPainter(img)
        paint_app_background(painter, QRectF(0, 0, 800, 600), dark=False, variant="home")
        painter.end()
    finally:
        bg_mod._HOME_LIGHT_PIXMAP = orig_pixmap
        bg_mod._HOME_LIGHT_LOADED = orig_loaded

    manager.apply("light")
    canvas.deleteLater()
    page.deleteLater()


def test_glass_header_and_shell_continuous_background_navigation(tmp_path: Path) -> None:
    from app.controllers import MainWindow
    from app.repositories.database import Database
    from app.ui.background import AppShell

    db = Database(tmp_path / "test.sqlite3")
    window = MainWindow(db)
    window.resize(1280, 800)
    window.show()
    QT_APP.processEvents()

    # 1. Trạng thái HomeScreen active
    assert isinstance(window.shell, AppShell)
    assert window.shell.home_background_active is True
    assert window.app_header.is_home_mode is True
    assert window.app_header.property("homeMode") == "true"
    assert window.shell.property("homeBackgroundActive") == "true"

    # 2. Chuyển sang SettingsScreen -> Tắt glass home mode ở shell & header
    window.show_settings()
    QT_APP.processEvents()
    assert window.shell.home_background_active is False
    assert window.app_header.is_home_mode is False
    assert window.app_header.property("homeMode") == "false"
    assert window.shell.property("homeBackgroundActive") == "false"

    # 3. Quay lại HomeScreen -> Bật lại glass home mode ở shell & header
    window.show_home()
    QT_APP.processEvents()
    assert window.shell.home_background_active is True
    assert window.app_header.is_home_mode is True
    assert window.app_header.property("homeMode") == "true"
    assert window.shell.property("homeBackgroundActive") == "true"

    window.thread_pool.waitForDone(2000)
    window.close()
    db.close()
