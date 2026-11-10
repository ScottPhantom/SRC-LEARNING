from __future__ import annotations

import csv
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QColor, QKeyEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
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
    LearningQuestionReview,
    Question,
    WeakQuestionReview,
)
from app.repositories.answer_key import AnswerKeyReport
from app.repositories.database import Database
from app.services.data_scanner import DataScannerService
from app.services.exam import ExamService
from app.services.package_catalog_source import PackageCatalogSource
from app.services.study import CrammingService, FlashcardService
from app.services.subject_management import SubjectInfo
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
from app.ui.subject_dashboard import QuestionBankNotificationDialog
from app.ui.subject_management_panel import SubjectManagementPanel
from app.ui.themes import DARK_STYLE, LIGHT_STYLE, ThemeManager

QT_APP = QApplication.instance() or QApplication([])


def make_subject(root: Path, amount: int = 2):
    for index in range(amount):
        path = root / "DATA" / "GUI101" / "Selections_1_choose" / f"Câu {index}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1000, 500), "white").save(path)
    return DataScannerService(root / "DATA").scan()[0]


def test_question_viewer_crops_answer_band_and_never_restores_it(
    tmp_path: Path,
) -> None:
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
        shortcut.context() == Qt.WindowShortcut for shortcut in viewer.zoom_in_shortcuts
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
    assert [
        screen.table.horizontalHeaderItem(column).text() for column in range(3)
    ] == [
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
    dashboard_top = screen.statistics_tabs.geometry().top()
    assert not any(
        button.text() == "Bắt đầu" for button in screen.findChildren(QPushButton)
    )
    selected_modes: list[str] = []
    screen.mode_selected.connect(selected_modes.append)
    QTest.mouseClick(screen.mode_cards["flash"], Qt.LeftButton)
    assert selected_modes == ["flash"]

    assert screen.dashboard_heading.text() == (
        f"Thống kê môn {subject.name} & Ôn tập nhanh"
    )
    assert [
        screen.statistics_tabs.tabText(index)
        for index in range(screen.statistics_tabs.count())
    ] == ["Câu chưa học", "Lỗi sai"]

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
    other_cards = [screen.mode_cards[mode] for mode in ("cram", "exam")]
    QApplication.sendEvent(card, QEvent(QEvent.Enter))
    QTest.qWait(280)
    assert card.property("hovered") is True
    assert card.minimumWidth() == card.minimumHeight() == 317
    assert card.shadow.blurRadius() >= 54
    assert screen.statistics_tabs.geometry().top() == dashboard_top
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
    screen.statistics_tabs.setCurrentIndex(1)
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


def test_learning_dashboard_rates_cards_and_updates_progress_directly(
    tmp_path: Path,
) -> None:
    subject = make_subject(tmp_path, 3)
    database = Database(tmp_path / "learning-dashboard.sqlite3")
    database.sync_questions(subject.questions, [subject.name])
    for question in subject.questions:
        database.rate_card(question.id, known=False)
    report = AnswerKeyReport(
        csv_path=subject.path / "answers.csv",
        file_found=True,
        total_rows=3,
        answers={
            question.relative_path: answer
            for question, answer in zip(subject.questions, "ABC", strict=True)
        },
    )
    learning_reviews = [
        LearningQuestionReview(
            question=question,
            correct_answer=report.answers[question.relative_path],
        )
        for question in subject.questions
    ]
    screen = ModeScreen(
        subject,
        report,
        database.card_stats(subject.name),
        {},
        (0.0, 0.9, 0.25, 0.1),
        learning_questions={"Selections_1_choose": learning_reviews},
    )
    screen.learning_status_changed.connect(database.rate_card)
    screen.resize(1280, 800)
    screen.show()
    table = screen.learning_tables["Selections_1_choose"]
    screen.learning_tabs.setCurrentWidget(table)
    QT_APP.processEvents()

    assert table.columnCount() == 2
    assert [table.horizontalHeaderItem(index).text() for index in range(2)] == [
        "Câu hỏi",
        "Trạng thái",
    ]
    assert [table.item(row, 0).text() for row in range(table.rowCount())] == [
        question.absolute_path.name for question in subject.questions
    ]
    assert all(
        table.item(row, 1).text() == "Chưa thuộc"
        and table.item(row, 1).foreground().color() == QColor("#FF453A")
        for row in range(table.rowCount())
    )

    table.cellDoubleClicked.emit(0, 0)
    QT_APP.processEvents()
    dialog = screen.quick_review_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.known_button is not None
    assert dialog.learning_button is not None

    QTest.mouseClick(dialog.learning_button, Qt.LeftButton)
    assert database.card_stats(subject.name)["learning"] == 3
    assert dialog.current_index == 1

    rated_known_id = subject.questions[1].id
    QTest.mouseClick(dialog.known_button, Qt.LeftButton)
    QT_APP.processEvents()
    assert rated_known_id not in database.learning_question_ids(subject.name)
    assert table.rowCount() == 2
    assert [table.item(row, 0).text() for row in range(2)] == [
        subject.questions[0].absolute_path.name,
        subject.questions[2].absolute_path.name,
    ]
    assert "1 đã thuộc" in screen.progress_summary.text()
    assert "2 chưa thuộc" in screen.progress_summary.text()

    dialog.close()
    screen.close()
    database.close()


def test_subject_dashboard_refreshes_after_new_question_bank_item(
    tmp_path: Path, monkeypatch
) -> None:
    subject = make_subject(tmp_path, 1)
    answers_path = subject.path / "answers.csv"
    with answers_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["image_name", "correct_answer"])
        writer.writerow([subject.questions[0].relative_path, "A"])

    database = Database(tmp_path / "dashboard-refresh.sqlite3")
    database.set_setting("data_dir", str(tmp_path / "DATA"))
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    window.watcher.blockSignals(True)
    window.show_modes(subject.name)
    old_page = window._dynamic_page
    assert isinstance(old_page, ModeScreen)
    assert old_page.learning_tables["Selections_1_choose"].rowCount() == 1

    new_image = subject.path / "Selections_1_choose" / "Câu 1.png"
    Image.new("RGB", (1000, 500), "white").save(new_image)
    with (subject.path / "answers.pending.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["image_name", "correct_answer"])
        writer.writerow(["Selections_1_choose/Câu 1.png", "B"])

    updated_subject = DataScannerService(tmp_path / "DATA").scan()[0]
    monkeypatch.setattr(window, "_show_pending_bank_notification", lambda *_args: None)
    window._apply_subjects([updated_subject])
    QT_APP.processEvents()

    refreshed_page = window._dynamic_page
    assert isinstance(refreshed_page, ModeScreen)
    assert refreshed_page is not old_page
    assert window.answer_reports[subject.name].valid_count == 2
    table = refreshed_page.learning_tables["Selections_1_choose"]
    displayed_names = [table.item(row, 0).text() for row in range(table.rowCount())]
    assert displayed_names == ["Câu 0.png", "Câu 1.png"]
    assert displayed_names.count("Câu 1.png") == 1
    added_question = next(
        question
        for question in updated_subject.questions
        if question.relative_path == "Selections_1_choose/Câu 1.png"
    )
    assert database.card_stats(subject.name) == {
        "new": 2,
        "known": 0,
        "learning": 0,
    }

    refreshed_page._handle_learning_rating(added_question.id, known=False)
    assert database.card_stats(subject.name) == {
        "new": 1,
        "known": 0,
        "learning": 1,
    }
    assert table.rowCount() == 2

    refreshed_page._handle_learning_rating(added_question.id, known=True)
    assert database.card_stats(subject.name) == {
        "new": 1,
        "known": 1,
        "learning": 0,
    }
    assert [table.item(row, 0).text() for row in range(table.rowCount())] == [
        "Câu 0.png"
    ]

    window.close()
    window.thread_pool.waitForDone(2000)
    window.deleteLater()
    QT_APP.processEvents()
    database.close()


def test_question_bank_notification_dialog_requires_every_slide_and_handles_delete(
    tmp_path: Path,
) -> None:
    subject = make_subject(tmp_path, 2)
    items = [
        {
            "item_index": 0,
            "change_type": "ADD",
            "logical_id": "add",
            "question_id": subject.questions[0].id,
            "old_path": None,
            "new_path": subject.questions[0].relative_path,
            "old_category": None,
            "new_category": "True_False",
            "old_answer": "",
            "new_answer": "B",
            "reason": "new-path",
            "viewed_at": None,
        },
        {
            "item_index": 1,
            "change_type": "UPDATE",
            "logical_id": "update",
            "question_id": subject.questions[1].id,
            "old_path": "Selections_1_choose/Câu 186.png",
            "new_path": subject.questions[1].relative_path,
            "old_category": "Selections_1_choose",
            "new_category": "Selections_Multiple_choose",
            "old_answer": "A",
            "new_answer": "AD",
            "reason": "category-changed+answer-changed",
            "viewed_at": None,
        },
        {
            "item_index": 2,
            "change_type": "DELETE",
            "logical_id": "delete",
            "question_id": "deleted-question",
            "old_path": "True_False/Câu 120.png",
            "new_path": None,
            "old_category": "True_False",
            "new_category": None,
            "old_answer": "B",
            "new_answer": "",
            "reason": "missing-from-data",
            "viewed_at": None,
        },
    ]
    dialog = QuestionBankNotificationDialog(
        subject.name,
        subject.path,
        2,
        items,
        (0.0, 0.9, 0.25, 0.1),
    )
    viewed: list[int] = []
    dialog.item_viewed.connect(viewed.append)
    ThemeManager(QT_APP).apply("light")
    dialog.show()
    QT_APP.processEvents()

    assert dialog.isModal()
    assert dialog.windowModality() == Qt.ApplicationModal
    assert not dialog.windowFlags() & Qt.WindowCloseButtonHint
    assert dialog.position_label.text() == "Thay đổi 1/3"
    assert dialog.change_badge.text() == "ADD"
    assert dialog.title_label.text().startswith("Đã bổ sung Câu")
    assert dialog.answer_label.text() == "B"
    assert viewed == [0]
    assert not dialog.finish_button.isVisible()
    assert dialog.previous_button.accessibleName()
    assert dialog.next_button.accessibleName()
    assert not dialog.previous_button.isEnabled()
    assert dialog.next_button.isEnabled()

    QTest.keyClick(dialog, Qt.Key_Escape)
    QTest.keyClick(dialog, Qt.Key_Space)
    QTest.keyClick(dialog, Qt.Key_Return)
    dialog.close()
    QT_APP.processEvents()
    assert dialog.isVisible()
    assert dialog.current_index == 0

    # Arrow navigation must work with focus inside the image viewer, not only
    # when the QDialog itself owns focus. Boundary keys keep the current slide.
    dialog.viewer.setFocus()
    QTest.keyClick(dialog.viewer, Qt.Key_Left)
    assert dialog.current_index == 0
    QTest.keyClick(dialog.viewer, Qt.Key_Right)
    assert dialog.current_index == 1
    assert dialog.change_badge.text() == "UPDATE"
    assert dialog.detail_label.text() == "Đáp án “A” → “A D”"
    assert dialog.content_stack.currentWidget() is dialog.viewer
    assert not dialog.finish_button.isVisible()
    assert dialog.previous_button.isEnabled()
    assert dialog.next_button.isEnabled()

    # The shortcut also remains active while a child button has focus.
    dialog.next_button.setFocus()
    QTest.keyClick(dialog.next_button, Qt.Key_Left)
    assert dialog.current_index == 0
    QTest.keyClick(dialog.next_button, Qt.Key_Right)
    assert dialog.current_index == 1
    QTest.keyClick(dialog.next_button, Qt.Key_Right)
    assert dialog.current_index == 2
    assert dialog.change_badge.text() == "DELETE"
    assert dialog.title_label.text() == "Câu 120 đã ngừng sử dụng"
    assert dialog.content_stack.currentWidget() is dialog.missing_frame
    assert "True_False/Câu 120.png" in dialog.missing_metadata.text()
    assert dialog.finish_button.isVisible() and dialog.finish_button.isEnabled()
    assert viewed == [0, 1, 2]
    assert dialog.previous_button.isEnabled()
    assert not dialog.next_button.isEnabled()
    QTest.keyClick(dialog.finish_button, Qt.Key_Right)
    assert dialog.current_index == 2
    QTest.keyClick(dialog.finish_button, Qt.Key_Left)
    assert dialog.current_index == 1
    QTest.keyClick(dialog.finish_button, Qt.Key_Right)
    assert dialog.current_index == 2

    assert not dialog.grab().isNull()
    ThemeManager(QT_APP).apply("dark")
    QT_APP.processEvents()
    assert not dialog.grab().isNull()
    dialog.completion_requested.connect(dialog.complete_and_close)
    QTest.mouseClick(dialog.finish_button, Qt.LeftButton)
    QT_APP.processEvents()
    assert not dialog.isVisible()
    ThemeManager(QT_APP).apply("light")
    dialog.deleteLater()


def test_question_bank_notification_opens_only_for_selected_subject_and_persists(
    tmp_path: Path,
) -> None:
    first_subject = make_subject(tmp_path, 2)
    other_image = tmp_path / "DATA" / "OTHER101" / "Selections_1_choose" / "Câu 1.png"
    other_image.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1000, 500), "white").save(other_image)
    subjects = DataScannerService(tmp_path / "DATA").scan()
    database_path = tmp_path / "notification-controller.sqlite3"
    database = Database(database_path)
    database.set_setting("data_dir", str(tmp_path / "DATA"))
    database.sync_questions(
        [question for subject in subjects for question in subject.questions],
        [subject.name for subject in subjects],
    )
    database.apply_question_bank_update(
        subject=first_subject.name,
        bank_version=2,
        revisions=[],
        updates=[],
        question_count=first_subject.question_count,
        added_count=1,
        deleted_count=0,
        notification_changes=[
            {
                "change_type": "ADD",
                "logical_id": first_subject.questions[0].id,
                "question_id": first_subject.questions[0].id,
                "old_path": None,
                "new_path": first_subject.questions[0].relative_path,
                "old_category": None,
                "new_category": first_subject.questions[0].category,
                "old_answer": "",
                "new_answer": "A",
                "reason": "new-path",
            },
            {
                "change_type": "UPDATE",
                "logical_id": first_subject.questions[1].id,
                "question_id": first_subject.questions[1].id,
                "old_path": first_subject.questions[1].relative_path,
                "new_path": first_subject.questions[1].relative_path,
                "old_category": first_subject.questions[1].category,
                "new_category": first_subject.questions[1].category,
                "old_answer": "B",
                "new_answer": "A",
                "reason": "answer-changed",
            },
        ],
    )

    window = MainWindow(database)
    window.show()
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    assert window.stack.currentWidget() is window.home
    assert window._bank_update_dialog is None

    window.show_modes("OTHER101")
    QT_APP.processEvents()
    assert window._bank_update_dialog is None

    window.show_modes(first_subject.name)
    QT_APP.processEvents()
    dialog = window._bank_update_dialog
    assert isinstance(dialog, QuestionBankNotificationDialog)
    assert dialog.subject == first_subject.name
    assert dialog.isVisible() and dialog.isModal()
    assert not dialog.finish_button.isVisible()

    QTest.keyClick(dialog, Qt.Key_Right)
    assert dialog.finish_button.isVisible()
    QTest.mouseClick(dialog.finish_button, Qt.LeftButton)
    QT_APP.processEvents()
    assert database.pending_question_bank_notification(first_subject.name) is None
    assert window._bank_update_dialog is None

    window.close()
    window.thread_pool.waitForDone(2000)
    window.deleteLater()
    database.close()

    reopened = Database(database_path)
    reopened.set_setting("data_dir", str(tmp_path / "DATA"))
    restarted_window = MainWindow(reopened)
    restarted_window.show()
    restarted_window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    assert restarted_window._bank_update_dialog is None
    restarted_window.show_modes(first_subject.name)
    QT_APP.processEvents()
    assert restarted_window._bank_update_dialog is None
    restarted_window.close()
    restarted_window.thread_pool.waitForDone(2000)
    restarted_window.deleteLater()
    reopened.close()


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
    for _ in range(50):
        if window.stack.currentWidget() is new_page:
            break
        QTest.qWait(20)
    assert window.stack.currentWidget() is new_page
    for _ in range(50):
        if not window._transition_in_progress:
            break
        QTest.qWait(20)
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
    assert [screen.tabs.tabText(index) for index in range(screen.tabs.count())] == [
        "Chung", "Quản lý môn học"
    ]
    assert screen.tabs.currentWidget() is screen.scroll_area
    screen.select_management_tab()
    assert screen.tabs.currentWidget() is screen.subject_management_panel
    assert screen.data_path.text() == str(tmp_path / "DATA")
    assert len(screen.crop_values) == 4
    screen.tabs.setCurrentWidget(screen.scroll_area)
    requested: list[str] = []
    screen.theme_preview_requested.connect(requested.append)

    screen.theme.setCurrentIndex(screen.theme.findData("dark"))

    assert requested == ["dark"]
    assert database.get_setting("theme") == "light"
    assert "tự dò" in screen.theme.toolTip()
    screen.deleteLater()
    database.close()


@pytest.mark.parametrize("width,height", [(1100, 700), (1280, 800), (2400, 900)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_settings_management_geometry_and_table_resize(
    width: int, height: int, theme: str
) -> None:
    ThemeManager(QT_APP).apply(theme)
    screen = SettingsScreen(AppSettings(theme=theme))
    path = Path("/Users/example/SRC-Project/SRC-LEARNING/DATA/AIL303m")
    panel = screen.subject_management_panel
    panel.set_subjects(
        [
            SubjectInfo("AIL303m", path, 154, 20_000_000, "Sẵn sàng"),
            SubjectInfo("ITE303c", path.parent / "ITE303c", 296, 18_000_000, "Sẵn sàng"),
        ]
    )
    screen.resize(width, height)
    screen.select_management_tab()
    screen.show()
    QT_APP.processEvents()

    tab_x = screen.tabs.mapTo(screen, QPoint(0, 0)).x()
    expected_x = screen.settings_container.mapTo(screen, QPoint(0, 0)).x() + 32
    assert tab_x == expected_x
    assert screen.settings_container.width() <= 1600
    assert panel.findChild(QWidget, "subjectManagementTitle").mapTo(
        screen, QPoint(0, 0)
    ).y() - screen.tabs.tabBar().mapTo(screen, QPoint(0, 0)).y() - screen.tabs.tabBar().height() >= 24

    tab_bar = screen.tabs.tabBar()
    heights = [tab_bar.tabRect(index).height() for index in range(2)]
    assert heights[0] == heights[1]
    assert tab_bar.tabRect(0).right() < tab_bar.tabRect(1).left()
    for index in range(2):
        label = screen.tabs.tabText(index)
        assert tab_bar.tabRect(index).width() >= tab_bar.fontMetrics().horizontalAdvance(label) + 20
    screen.tabs.setCurrentIndex(0)
    QT_APP.processEvents()
    assert [tab_bar.tabRect(index).height() for index in range(2)] == heights
    assert tab_bar.focusPolicy() == Qt.StrongFocus
    assert "QTabWidget#settingsTabs QTabBar::tab:focus" in (
        DARK_STYLE if theme == "dark" else LIGHT_STYLE
    )
    tab_bar.clearFocus()
    QT_APP.processEvents()
    unfocused_tabs = tab_bar.grab().toImage()
    tab_bar.setFocus()
    QT_APP.processEvents()
    assert tab_bar.hasFocus()
    assert tab_bar.grab().toImage() != unfocused_tabs

    screen.select_management_tab()
    QT_APP.processEvents()
    header = panel.table.horizontalHeader()
    assert [header.sectionResizeMode(i) for i in range(5)] == [
        QHeaderView.ResizeToContents,
        QHeaderView.Fixed,
        QHeaderView.Fixed,
        QHeaderView.Stretch,
        QHeaderView.ResizeToContents,
    ]
    assert not header.stretchLastSection()
    assert panel.table.columnWidth(3) > panel.table.columnWidth(4) * 2
    assert panel.table.item(0, 3).toolTip() == str(path)
    assert panel.table.height() < 200
    screen.close()
    screen.deleteLater()
    ThemeManager(QT_APP).apply("light")


def test_settings_management_table_scrolls_when_many_subjects() -> None:
    screen = SettingsScreen(AppSettings())
    panel = screen.subject_management_panel
    panel.set_subjects(
        [
            SubjectInfo(f"COURSE{index:02d}", Path(f"/DATA/COURSE{index:02d}"), 10, 5000, "Sẵn sàng")
            for index in range(20)
        ]
    )
    screen.resize(1100, 700)
    screen.select_management_tab()
    screen.show()
    QT_APP.processEvents()
    assert panel.table.rowCount() == 20
    assert panel.table.height() < 350
    assert panel.table.verticalScrollBar().maximum() > 0
    screen.close()
    screen.deleteLater()


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
    QT_APP.processEvents()
    window.close()
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
    assert all(
        not widget.isEnabled() for widget in screen.answer_options.option_widgets
    )
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
    first_session = ExamService(database, subject.questions, answers).create_session(
        config
    )
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
    second_session = ExamService(database, subject.questions, answers).create_session(
        config
    )
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

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Cancel
    )
    QTest.mouseClick(page.delete_button, Qt.LeftButton)
    assert len(database.exam_history()) == 2

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes
    )
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


def test_cramming_right_arrow_requires_enter_and_does_not_mutate_queue(
    tmp_path: Path,
) -> None:
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
    path = tmp_path / "DATA" / "GUI101" / "Selections_Multiple_choose" / "Câu nhiều.png"
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


def test_single_choice_fifth_option_can_be_selected_and_graded(tmp_path: Path) -> None:
    question = Question(
        id="five-options",
        subject="SSG105",
        category="Selections_1_choose",
        relative_path="Selections_1_choose/Q107.png",
        absolute_path=tmp_path / "Q107.png",
        option_letters=tuple("ABCDE"),
    )
    widget = AnswerOptionsWidget()
    widget.set_question(question)
    assert widget.toggle_option("E")
    assert widget.selected_answer() == "E"
    assert widget.toggle_option("A")
    assert widget.selected_answer() == "A"
    widget.show_feedback(question, "E", "E")
    assert widget.option_widgets[4].property("answerState") == "correct"
    widget.deleteLater()


def test_answer_sidebar_fits_four_choices_and_resizes_for_each_question(
    tmp_path: Path,
) -> None:
    from app.ui.assessment_sidebar import AssessmentSidebar

    sidebar = AssessmentSidebar()
    sidebar.resize(330, 700)
    sidebar.navigation.set_count(154)
    sidebar.add_action(QPushButton("Xác nhận đáp án"))
    sidebar.add_action_row(QPushButton("Câu trước"), QPushButton("Câu sau"))
    sidebar.add_action(QPushButton("Nộp bài"))
    sidebar.show()

    def question(category: str, options: str = "") -> Question:
        return Question(
            id=f"{category}-{options}",
            subject="GUI101",
            category=category,
            relative_path="question.png",
            absolute_path=tmp_path / "question.png",
            option_letters=tuple(options),
        )

    sidebar.answer_options.set_question(question("Selections_1_choose"))
    QT_APP.processEvents()
    assert [button.text() for button in sidebar.answer_options.option_widgets] == list("ABCD")
    assert sidebar.answer_scroll.verticalScrollBar().maximum() == 0
    assert sidebar.answer_options.option_widgets[-1].geometry().bottom() < sidebar.answer_scroll.viewport().height()

    sidebar.answer_options.set_question(question("Selections_1_choose", "ABCDE"))
    QT_APP.processEvents()
    assert [button.text() for button in sidebar.answer_options.option_widgets] == list("ABCDE")
    assert sidebar.answer_scroll.verticalScrollBar().maximum() == 0
    assert sidebar.answer_options.option_widgets[-1].geometry().bottom() < sidebar.answer_scroll.viewport().height()

    sidebar.answer_options.set_question(question("Selections_Multiple_choose", "ABCDEFGHIJKL"))
    QT_APP.processEvents()
    assert len(sidebar.answer_options.option_widgets) == 12
    assert sidebar.answer_scroll.verticalScrollBar().maximum() > 0

    sidebar.answer_options.set_question(question("True_False", "ABCDE"))
    QT_APP.processEvents()
    assert [button.text() for button in sidebar.answer_options.option_widgets] == ["True", "False"]
    assert [button.shortcut_hint.text() for button in sidebar.answer_options.option_widgets] == ["A", "B"]
    assert sidebar.answer_scroll.verticalScrollBar().maximum() == 0
    assert sidebar.answer_options.toggle_option("A")
    assert sidebar.answer_options.selected_answer() == "A"
    assert sidebar.answer_options.toggle_option("B")
    assert sidebar.answer_options.selected_answer() == "B"
    assert not sidebar.answer_options.toggle_option("C")
    sidebar.close()
    sidebar.deleteLater()


def test_more_than_e_options_remain_selectable_and_scroll_in_sidebar(tmp_path: Path) -> None:
    from app.ui.assessment_sidebar import AssessmentSidebar

    question = Question(
        id="twelve-options",
        subject="SSG105",
        category="Selections_Multiple_choose",
        relative_path="Selections_Multiple_choose/Q012.png",
        absolute_path=tmp_path / "Q012.png",
        option_letters=tuple("ABCDEFGHIJKL"),
    )
    sidebar = AssessmentSidebar()
    sidebar.resize(330, 700)
    sidebar.answer_options.set_question(question)
    sidebar.show()
    QT_APP.processEvents()
    assert len(sidebar.answer_options.option_widgets) == 12
    assert sidebar.answer_options.option_widgets[9].shortcut_hint.text() == "J"
    assert sidebar.answer_scroll.verticalScrollBar().maximum() > 0
    assert sidebar.answer_options.toggle_option("J")
    assert sidebar.answer_options.toggle_option("L")
    assert sidebar.answer_options.selected_answer() == "JL"
    sidebar.close()
    sidebar.deleteLater()


def test_exam_can_select_and_grade_tenth_option_by_letter(tmp_path: Path) -> None:
    from dataclasses import replace

    subject = make_subject(tmp_path, 1)
    question = replace(subject.questions[0], option_letters=tuple("ABCDEFGHIJ"))
    database = Database(tmp_path / "exam-tenth-option.sqlite3")
    database.sync_questions([question], [question.subject])
    session = ExamService(database, [question], {question.relative_path: "J"}).create_session(
        ExamConfig(
            subject=question.subject,
            categories=(question.category,),
            question_count=1,
            duration_minutes=1,
            feedback_mode=FeedbackMode.DEFERRED,
        )
    )
    screen = ExamScreen(session, (0.0, 0.9, 0.25, 0.1))
    screen.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_J, Qt.NoModifier))
    assert session.current.selected_answer == "J"
    assert session.submit().correct == 1
    screen._timer.stop()
    screen.deleteLater()
    database.close()


def test_exam_true_false_buttons_use_a_b_hotkeys(tmp_path: Path) -> None:
    image_path = tmp_path / "DATA" / "GUI101" / "True_False" / "Câu đúng sai.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1000, 500), "white").save(image_path)
    question = DataScannerService(tmp_path / "DATA").scan()[0].questions[0]
    question.option_letters = tuple("ABCDE")
    database = Database(tmp_path / "exam-true-false.sqlite3")
    database.sync_questions([question], [question.subject])
    session = ExamService(
        database, [question], {question.relative_path: "B"}
    ).create_session(
        ExamConfig(
            subject=question.subject,
            categories=("True_False",),
            question_count=1,
            duration_minutes=1,
            feedback_mode=FeedbackMode.DEFERRED,
        )
    )
    screen = ExamScreen(session, (0.0, 0.9, 0.25, 0.1))
    assert [button.text() for button in screen.answer_options.option_widgets] == ["True", "False"]
    screen.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier))
    assert session.current.selected_answer == "A"
    screen.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_B, Qt.NoModifier))
    assert session.current.selected_answer == "B"
    screen.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_C, Qt.NoModifier))
    assert session.current.selected_answer == "B"
    assert session.submit().correct == 1
    screen._timer.stop()
    screen.deleteLater()
    database.close()


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
    assert len(home._card_widgets) == 1
    card1 = home._card_widgets[subject1.name]
    assert isinstance(card1, SubjectCard)
    assert any(
        home.cards_grid.itemAt(index).widget() is card1
        for index in range(home.cards_grid.count())
    )
    assert card1.title_label.text() == subject1.name
    assert f"{subject1.question_count} câu hỏi" in card1.count_label.text()
    assert "Multiple_choose" not in card1.title_label.text()

    # Test set_subjects với 3 môn
    subject2 = make_subject(tmp_path, 1)
    subject2.name = "CS101"
    subject3 = make_subject(tmp_path, 4)
    subject3.name = "PHY202"
    home.set_subjects([subject1, subject2, subject3], data_dir)
    assert len(home._card_widgets) == 3
    assert any(
        header.text() == "Chưa phân loại"
        for header in home._section_headers.values()
    )
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

    data_import_calls = []
    history_calls = []
    refresh_calls = []
    settings_calls = []

    header.data_import_requested.connect(lambda: data_import_calls.append(True))
    header.history_requested.connect(lambda: history_calls.append(True))
    header.refresh_requested.connect(lambda: refresh_calls.append(True))
    header.settings_requested.connect(lambda: settings_calls.append(True))

    header.data_import_button.click()
    header.history_button.click()
    header.refresh_button.click()
    header.settings_button.click()

    assert len(data_import_calls) == 1
    assert len(history_calls) == 1
    assert len(refresh_calls) == 1
    assert len(settings_calls) == 1
    assert not hasattr(header, "subject_management_button")

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


def test_data_import_dialog_requires_code_and_emits_request() -> None:
    from app.ui.data_import_dialog import DataImportDialog

    dialog = DataImportDialog()
    emitted: list[str] = []
    dialog.install_requested.connect(emitted.append)
    dialog.show()
    QT_APP.processEvents()

    dialog.install_button.click()
    assert not emitted
    assert "Hãy nhập" in dialog.status_label.text()

    dialog.code_input.setText("1r82uwHDR7LVfpVv74W75OZ6xWh-2odrP")
    dialog.install_button.click()
    assert emitted == ["1r82uwHDR7LVfpVv74W75OZ6xWh-2odrP"]

    dialog.set_running(True)
    assert not dialog.code_input.isEnabled()
    assert dialog.progress_bar.isVisible()
    dialog.update_progress("extract", 62, "Đang giải nén…")
    assert dialog.progress_bar.value() == 62
    assert dialog.status_label.text() == "Đang giải nén…"

    dialog.set_running(False)
    dialog.close()


def test_subject_management_delete_keeps_progress_and_refreshes_home(
    tmp_path: Path, monkeypatch
) -> None:
    from PyQt5.QtWidgets import QInputDialog

    subject = make_subject(tmp_path, 1)
    database = Database(tmp_path / "manage.sqlite3")
    database.set_setting("data_dir", str(tmp_path / "DATA"))
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    database.rate_card(subject.questions[0].id, known=False)
    window.show_subject_management()
    dialog = window._management_panel()
    assert isinstance(dialog, SubjectManagementPanel)
    assert isinstance(window._dynamic_page, SettingsScreen)
    assert window._dynamic_page.tabs.currentWidget() is dialog
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).text() == "GUI101"
    assert dialog.table.item(0, 1).text() == "1"
    assert dialog.table.item(0, 3).text() == str(subject.path)
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args: ("WRONG", True))
    window._delete_subject(subject.name)
    assert subject.path.exists()
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args: (subject.name, True))
    window._delete_subject(subject.name)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    assert not subject.path.exists()
    assert subject.name not in window.subjects
    assert dialog.table.rowCount() == 0
    row = database._connection.execute(
        "SELECT q.active, p.state FROM questions q JOIN card_progress p ON p.question_id=q.id WHERE q.id=?",
        (subject.questions[0].id,),
    ).fetchone()
    assert tuple(row) == (0, "learning")
    assert str(subject.path) not in window.watcher.directories(), window.watcher.directories()
    assert (tmp_path / ".src-learning-recovery").is_dir()
    window.close()
    window.thread_pool.waitForDone(2000)
    database.close()


def test_subject_management_confirms_cancel_active_learning_session(tmp_path: Path, monkeypatch) -> None:
    from PyQt5.QtWidgets import QInputDialog

    subject = make_subject(tmp_path, 1)
    database = Database(tmp_path / "manage-active.sqlite3")
    database.set_setting("data_dir", str(tmp_path / "DATA"))
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    database.create_flash_session(subject.name, [subject.questions[0].id])
    window.show_subject_management()
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args: (subject.name, True))
    monkeypatch.setattr(window, "_ask_cancel_active_learning", lambda _name: False)
    window._delete_subject(subject.name)
    assert subject.path.is_dir()
    assert database.active_flash_session(subject.name) is not None
    assert "giữ phiên" in window._management_panel().status_label.text()
    monkeypatch.setattr(window, "_ask_cancel_active_learning", lambda _name: True)
    window._delete_subject(subject.name)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    assert not subject.path.exists()
    assert database.active_flash_session(subject.name) is None
    window.close()
    window.thread_pool.waitForDone(2000)
    database.close()


def test_settings_management_tab_opens_import_from_add_button(tmp_path: Path) -> None:
    from app.ui.data_import_dialog import DataImportDialog

    data = tmp_path / "DATA"
    data.mkdir()
    database = Database(tmp_path / "settings-add.sqlite3")
    database.set_setting("data_dir", str(data))
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    window.show_settings()
    page = window._dynamic_page
    assert isinstance(page, SettingsScreen)
    page.select_management_tab()
    page.subject_management_panel.add_button.click()
    assert isinstance(window._data_import_dialog, DataImportDialog)
    window._data_import_dialog.reject()
    window.close()
    window.thread_pool.waitForDone(2000)
    database.close()


def test_subject_management_cancels_active_cram_without_erasing_progress(
    tmp_path: Path, monkeypatch
) -> None:
    from PyQt5.QtWidgets import QInputDialog

    subject = make_subject(tmp_path, 1)
    database = Database(tmp_path / "manage-cram.sqlite3")
    database.set_setting("data_dir", str(tmp_path / "DATA"))
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    database.rate_card(subject.questions[0].id, known=False)
    database.create_cram_cycle(subject.name, 1, [[subject.questions[0].id]])
    window.show_subject_management()
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args: (subject.name, True))
    monkeypatch.setattr(window, "_ask_cancel_active_learning", lambda _name: True)
    window._delete_subject(subject.name)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    assert not subject.path.exists()
    assert database.active_cram_cycle(subject.name) is None
    row = database._connection.execute(
        "SELECT state FROM card_progress WHERE question_id=?", (subject.questions[0].id,)
    ).fetchone()
    assert row[0] == "learning"
    window.close()
    window.thread_pool.waitForDone(2000)
    database.close()


def test_settings_management_requires_exam_exit_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    subject = make_subject(tmp_path, 1)
    database = Database(tmp_path / "manage-exam.sqlite3")
    database.set_setting("data_dir", str(tmp_path / "DATA"))
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    window.current_subject = subject
    config = ExamConfig(
        subject=subject.name,
        categories=("Selections_1_choose",),
        question_count=1,
        duration_minutes=10,
        feedback_mode=FeedbackMode.DEFERRED,
    )
    session = ExamService(
        database, subject.questions, {subject.questions[0].relative_path: "A"}
    ).create_session(config)
    window.start_exam(session)
    monkeypatch.setattr(window, "_ask_active_exam_exit", lambda: "cancel")
    window.show_settings(management=True)
    assert window.active_exam_screen is not None
    assert isinstance(window._dynamic_page, ExamScreen)
    monkeypatch.setattr(window, "_ask_active_exam_exit", lambda: "discard")
    window.show_settings(management=True)
    assert window.active_exam_screen is None
    assert isinstance(window._dynamic_page, SettingsScreen)
    assert window._dynamic_page.tabs.currentWidget() is window._management_panel()
    window.close()
    window.thread_pool.waitForDone(2000)
    database.close()


def test_existing_subject_import_cancel_keeps_files(tmp_path: Path, monkeypatch) -> None:
    from app.ui.data_import_dialog import DataImportDialog

    data = tmp_path / "DATA"
    subject_path = data / "AIL303m"
    subject_path.mkdir(parents=True)
    (subject_path / "keep.txt").write_text("old", encoding="utf-8")
    database = Database(tmp_path / "import-guard.sqlite3")
    database.set_setting("data_dir", str(data))
    window = MainWindow(database)
    # Cancellation should not depend on the public Sheet or a developer cache.
    window._catalog_source = PackageCatalogSource("", tmp_path / "catalog.csv")
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    window.show_data_import()
    dialog = window._data_import_dialog
    assert isinstance(dialog, DataImportDialog)
    code = "1r82uwHDR7LVfpVv74W75OZ6xWh-2odrP"
    monkeypatch.setattr(QMessageBox, "exec_", lambda _self: 0)
    window._start_data_install(code)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    assert window._data_install_task is None
    assert (subject_path / "keep.txt").read_text(encoding="utf-8") == "old"
    assert "Đã hủy" in dialog.status_label.text()
    dialog.reject()
    window.close()
    window.thread_pool.waitForDone(2000)
    database.close()


def test_import_checks_new_code_from_remote_catalog(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "DATA"
    subject_path = data / "CPV301"
    subject_path.mkdir(parents=True)
    (subject_path / "keep.txt").write_text("old", encoding="utf-8")
    database = Database(tmp_path / "remote-catalog.sqlite3")
    database.set_setting("data_dir", str(data))
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    csv_data = (
        "Môn,Google file ID,Số câu,SHA-256 ZIP,Kích thước (byte),App manifest\n"
        f"CPV301,new-approved-drive-id,89,{'a' * 64},21423181,Đã bật\n"
    ).encode()
    window._catalog_source = PackageCatalogSource(
        "https://docs.google.com/spreadsheets/d/e/example/pub?gid=105&output=csv",
        tmp_path / "catalog.csv",
        fetch=lambda _url: csv_data,
    )
    window.show_data_import()
    dialog = window._data_import_dialog
    assert dialog is not None
    monkeypatch.setattr(QMessageBox, "exec_", lambda _self: 0)
    window._start_data_install("new-approved-drive-id")
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    assert window._data_package_installer.catalog.resolve("new-approved-drive-id").subject == "CPV301"
    assert "Đã hủy" in dialog.status_label.text()
    assert (subject_path / "keep.txt").read_text(encoding="utf-8") == "old"
    dialog.reject()
    window.close()
    window.thread_pool.waitForDone(2000)
    database.close()


def test_delete_restores_files_when_database_sync_fails(tmp_path: Path, monkeypatch) -> None:
    from PyQt5.QtWidgets import QInputDialog

    subject = make_subject(tmp_path, 1)
    database = Database(tmp_path / "rollback-delete.sqlite3")
    database.set_setting("data_dir", str(tmp_path / "DATA"))
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    window.show_subject_management()
    original_sync = database.sync_questions
    calls = 0

    def fail_once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("database unavailable")
        return original_sync(*args)

    monkeypatch.setattr(database, "sync_questions", fail_once)
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args: (subject.name, True))
    window._delete_subject(subject.name)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    assert subject.path.is_dir()
    assert subject.name in window.subjects
    assert "đã khôi phục" in window._management_panel().status_label.text()
    window.close()
    window.thread_pool.waitForDone(2000)
    database.close()


def test_replace_restores_files_when_database_sync_fails(tmp_path: Path, monkeypatch) -> None:
    from app.services.data_package_installer import DataInstallResult
    from app.services.subject_management import SubjectManager

    subject = make_subject(tmp_path, 1)
    (subject.path / "old.txt").write_text("original", encoding="utf-8")
    database = Database(tmp_path / "rollback-replace.sqlite3")
    database.set_setting("data_dir", str(tmp_path / "DATA"))
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    # The UI removes QFileSystemWatcher handles before moving a subject on
    # Windows; this direct service setup must do the same.
    watched_paths = window.watcher.directories() + window.watcher.files()
    if watched_paths:
        window.watcher.removePaths(watched_paths)
    backup = SubjectManager(tmp_path / "DATA").remove(subject.name)
    subject.path.mkdir()
    (subject.path / "new.txt").write_text("new", encoding="utf-8")
    original_sync = database.sync_questions
    calls = 0

    def fail_once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("database unavailable")
        return original_sync(*args)

    monkeypatch.setattr(database, "sync_questions", fail_once)
    window._data_install_completed(
        DataInstallResult(subject.name, subject.path, 1, "a" * 64, backup)
    )
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    assert (subject.path / "old.txt").read_text(encoding="utf-8") == "original"
    assert not (subject.path / "new.txt").exists()
    assert subject.name in window.subjects
    window.close()
    window.thread_pool.waitForDone(2000)
    database.close()


def test_drive_replacement_restores_old_subject_when_answer_version_fails(
    tmp_path: Path, monkeypatch
) -> None:
    from app.services.data_package_installer import DataInstallResult
    from app.services.question_bank_updates import (
        BankUpdateResult,
        QuestionBankUpdateChecker,
        stage_replacement_answer_history,
    )
    from app.services.subject_management import SubjectManager

    old = make_subject(tmp_path, 1)
    with (old.path / "answers.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["image_name", "correct_answer"])
        writer.writerow(["Selections_1_choose/Câu 0.png", "A"])
    (old.path / "old.txt").write_text("original", encoding="utf-8")
    database = Database(tmp_path / "rollback-bank.sqlite3")
    database.set_setting("data_dir", str(tmp_path / "DATA"))
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    assert database.latest_bank_version(old.name) == 1

    watched = window.watcher.directories() + window.watcher.files()
    if watched:
        window.watcher.removePaths(watched)
    backup = SubjectManager(tmp_path / "DATA").remove(old.name)
    new = make_subject(tmp_path, 2)
    with (new.path / "answers.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["image_name", "correct_answer"])
        writer.writerows([
            ["Selections_1_choose/Câu 0.png", "A"],
            ["Selections_1_choose/Câu 1.png", "A"],
        ])
    (new.path / "new.txt").write_text("incoming", encoding="utf-8")
    assert stage_replacement_answer_history(backup, new.path, new.name) == 1
    window.show_data_import()
    window._pending_data_install_result = DataInstallResult(
        new.name, new.path, 2, "a" * 64, backup, previous_bank_version=1
    )
    monkeypatch.setattr(window, "refresh_data", lambda: None)
    monkeypatch.setattr(
        QuestionBankUpdateChecker,
        "check",
        lambda _self, _subjects, *, apply=True: [
            BankUpdateResult(subject=new.name, errors=["giả lập lỗi lưu phiên bản"])
        ],
    )

    window._apply_subjects([new])

    assert (old.path / "old.txt").read_text(encoding="utf-8") == "original"
    assert not (old.path / "new.txt").exists()
    assert window._pending_data_install_result is None
    assert database.latest_bank_version(old.name) == 1
    assert "đã khôi phục" in window._data_import_dialog.status_label.text()
    window._data_import_dialog.reject()
    window.close()
    window.thread_pool.waitForDone(2000)
    database.close()


def test_drive_replacement_reports_success_after_answer_version_is_saved(
    tmp_path: Path,
) -> None:
    from app.services.data_package_installer import DataInstallResult
    from app.services.question_bank_updates import stage_replacement_answer_history
    from app.services.subject_management import SubjectManager

    old = make_subject(tmp_path, 1)
    with (old.path / "answers.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["image_name", "correct_answer"])
        writer.writerow(["Selections_1_choose/Câu 0.png", "A"])
    database = Database(tmp_path / "success-bank.sqlite3")
    database.set_setting("data_dir", str(tmp_path / "DATA"))
    window = MainWindow(database)
    window.thread_pool.waitForDone(2000)
    QT_APP.processEvents()
    assert database.latest_bank_version(old.name) == 1

    watched = window.watcher.directories() + window.watcher.files()
    if watched:
        window.watcher.removePaths(watched)
    backup = SubjectManager(tmp_path / "DATA").remove(old.name)
    new = make_subject(tmp_path, 2)
    with (new.path / "answers.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["image_name", "correct_answer"])
        writer.writerows([
            ["Selections_1_choose/Câu 0.png", "A"],
            ["Selections_1_choose/Câu 1.png", "A"],
        ])
    assert stage_replacement_answer_history(backup, new.path, new.name) == 1
    window.show_data_import()

    window._data_install_completed(
        DataInstallResult(new.name, new.path, 2, "a" * 64, backup, previous_bank_version=1)
    )
    for _ in range(3):
        window.thread_pool.waitForDone(2000)
        QT_APP.processEvents()

    assert database.latest_bank_version(new.name) == 2
    assert window._pending_data_install_result is None
    assert window._data_import_dialog._completed
    assert "answer bank v2" in window._data_import_dialog.status_label.text()
    assert (new.path / "answer_versions" / "answers.v1.csv").is_file()
    assert (new.path / "answer_versions" / "answers.v2.csv").is_file()
    window._data_import_dialog.accept()
    window.close()
    window.thread_pool.waitForDone(2000)
    database.close()


def test_history_tree_groups_subjects_formats_local_time_and_selects_only_exams() -> (
    None
):
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
    assert home.cards_grid.alignment() & Qt.AlignTop
    home.deleteLater()


def test_home_groups_courses_and_shows_three_cards_per_desktop_row(
    tmp_path: Path,
) -> None:
    from app.domain.models import Subject
    from app.ui.screens import HomeScreen

    home = HomeScreen()
    home.resize(1280, 800)
    home.show()
    QT_APP.processEvents()
    subjects = [
        Subject(name=name, path=tmp_path / name)
        for name in ("SSG105", "ITE303c", "DAP391m", "AIL303m", "CPV301")
    ]
    next_year_path = tmp_path / "NEW101"
    next_year_path.mkdir()
    (next_year_path / "academic_term.json").write_text(
        '{"year": 2027, "semester": "SP"}', encoding="utf-8"
    )
    subjects.append(Subject(name="NEW101", path=next_year_path))
    home.set_subjects(subjects, tmp_path / "DATA")
    QT_APP.processEvents()

    assert home._current_cols >= 3
    headers = [header.text() for header in home._section_headers.values()]
    assert any(text.startswith("Năm 2026") for text in headers)
    assert any(text.startswith("Năm 2027") for text in headers)
    assert any("SU26 · Summer 2026" in text for text in headers)
    assert any("FA26 · Fall 2026" in text for text in headers)

    def card_position(name: str) -> tuple[int, int]:
        for index in range(home.cards_grid.count()):
            if home.cards_grid.itemAt(index).widget() is home._card_widgets[name]:
                row, column, _, _ = home.cards_grid.getItemPosition(index)
                return row, column
        raise AssertionError(f"Card {name} is missing")

    assert card_position("AIL303m")[0] == card_position("CPV301")[0]
    assert card_position("CPV301")[0] == card_position("DAP391m")[0]
    assert [card_position(name)[1] for name in ("AIL303m", "CPV301", "DAP391m")] == [0, 1, 2]
    assert card_position("NEW101")[0] < card_position("AIL303m")[0]
    assert card_position("AIL303m")[0] < card_position("ITE303c")[0]
    assert home._section_headers[("year", "2027")].geometry().top() < home._section_headers[("year", "2026")].geometry().top()
    ite = home._card_widgets["ITE303c"]
    fall_header = home._section_headers[("term", "FA26")]
    summer_header = home._section_headers[("term", "SU26")]
    assert fall_header.geometry().bottom() < home._card_widgets["AIL303m"].geometry().top()
    assert home._card_widgets["AIL303m"].geometry().bottom() < summer_header.geometry().top()
    assert summer_header.geometry().bottom() < ite.geometry().top()
    assert home.canvas.height() > home.scroll_area.viewport().height()
    home.resize(1100, 700)
    home._reflow_grid(force=True)
    QT_APP.processEvents()
    assert home._current_cols >= 3
    assert all(home._card_widgets[name].width() >= 300 for name in ("AIL303m", "CPV301", "DAP391m"))
    home.close()
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
        image.pixelColor(x, y).alpha() > 0 for x in range(w // 2) for y in range(h // 2)
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

    assert quad1 and quad2 and quad3 and quad4, (
        "Reload icon phải vẽ dạng vòng tròn phủ cả 4 góc phần tư"
    )
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
        paint_app_background(
            painter, QRectF(0, 0, 800, 600), dark=False, variant="home"
        )
        painter.end()
    finally:
        bg_mod._HOME_LIGHT_PIXMAP = orig_pixmap
        bg_mod._HOME_LIGHT_LOADED = orig_loaded

    manager.apply("light")
    canvas.deleteLater()
    page.deleteLater()


def test_glass_header_and_shell_continuous_background_navigation(
    tmp_path: Path,
) -> None:
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
