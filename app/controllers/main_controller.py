from __future__ import annotations

import logging
from pathlib import Path

from PyQt5.QtCore import (
    QByteArray,
    QEasingCurve,
    QFileSystemWatcher,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    Qt,
    QThreadPool,
    QTimer,
)
from PyQt5.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
)

from app.config import APP_NAME, DEFAULT_DATA_DIR
from app.controllers.scan_worker import ScanTask
from app.domain.models import AppSettings, ExamConfig, Subject
from app.repositories.answer_key import AnswerKeyReport, AnswerKeyRepository
from app.repositories.database import Database
from app.services.adaptive import AdaptiveReviewService
from app.services.exam import ExamResult, ExamService, ExamSession
from app.services.question_bank_updates import (
    PENDING_ANSWERS_FILE,
    BankUpdateResult,
    QuestionBankUpdateChecker,
)
from app.services.study import CrammingService, FlashcardService
from app.ui.background import AppShell
from app.ui.screens import (
    AppHeader,
    CrammingScreen,
    ExamConfigScreen,
    ExamScreen,
    FlashcardScreen,
    HistoryScreen,
    HomeScreen,
    ModeScreen,
    ResultScreen,
    SettingsScreen,
)
from app.ui.themes import ThemeManager

LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, database: Database):
        super().__init__()
        self.database = database
        self.settings = database.load_app_settings(DEFAULT_DATA_DIR)
        self.data_dir = Path(self.settings.data_dir).expanduser().resolve()
        self.subjects: dict[str, Subject] = {}
        self.answer_reports: dict[str, AnswerKeyReport] = {}
        self.current_subject: Subject | None = None
        self.active_exam_screen: ExamScreen | None = None
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1100, 700)
        geometry = self.database.get_setting("window_geometry", "")
        if geometry:
            self.restoreGeometry(QByteArray.fromHex(geometry.encode("ascii")))
        # Khởi động nhất quán ở kích thước thiết kế; restoreGeometry vẫn giữ vị trí.
        self.resize(1280, 800)
        shell = AppShell()
        shell.setObjectName("appShell")
        self.shell = shell
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self.app_header = AppHeader()
        self.app_header.home_requested.connect(self.show_home)
        self.app_header.history_requested.connect(self.show_history)
        self.app_header.refresh_requested.connect(self.refresh_data)
        self.app_header.settings_requested.connect(self.show_settings)
        shell_layout.addWidget(self.app_header)
        self.stack = QStackedWidget()
        self.stack.setObjectName("contentStack")
        self.stack.setAttribute(Qt.WA_TranslucentBackground, True)
        self.stack.setAutoFillBackground(False)
        shell_layout.addWidget(self.stack, 1)
        self.setCentralWidget(shell)
        self.home = HomeScreen()
        self.home.subject_selected.connect(self.show_modes)
        self.home.refresh_requested.connect(self.refresh_data)
        self.home.settings_requested.connect(self.show_settings)
        self.home.history_requested.connect(self.show_history)
        self.stack.addWidget(self.home)
        self._dynamic_page = None
        self._transition_group: QSequentialAnimationGroup | None = None
        self._transition_in_progress = False
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._schedule_refresh)
        self.watcher.fileChanged.connect(self._schedule_refresh)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(450)
        self.refresh_timer.timeout.connect(self.refresh_data)
        self.thread_pool = QThreadPool.globalInstance()
        self._scan_running = False
        self._rescan_requested = False
        self._bank_update_dialogs: list[QMessageBox] = []
        self.theme_manager = ThemeManager(QApplication.instance())
        self._apply_theme(self.settings.theme)
        self.refresh_data()

    def _set_dynamic_page(self, page, animate: bool = False) -> None:
        self.app_header.set_home_mode(False)
        self.shell.set_home_background_active(False)
        previous = self._dynamic_page
        self._dynamic_page = page
        self.stack.addWidget(page)
        current = self.stack.currentWidget()
        if not animate or current is None:
            self.stack.setCurrentWidget(page)
            if previous is not None:
                self.stack.removeWidget(previous)
                previous.deleteLater()
            return

        self._transition_in_progress = True
        old_effect = QGraphicsOpacityEffect(current)
        old_effect.setOpacity(1.0)
        current.setGraphicsEffect(old_effect)
        new_effect = QGraphicsOpacityEffect(page)
        new_effect.setOpacity(0.0)
        page.setGraphicsEffect(new_effect)

        fade_out = QPropertyAnimation(old_effect, b"opacity", self)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setDuration(150)
        fade_out.setEasingCurve(QEasingCurve.InOutCubic)
        fade_in = QPropertyAnimation(new_effect, b"opacity", self)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setDuration(150)
        fade_in.setEasingCurve(QEasingCurve.InOutCubic)
        group = QSequentialAnimationGroup(self)
        group.addAnimation(fade_out)
        group.addAnimation(fade_in)
        fade_out.finished.connect(lambda: self.stack.setCurrentWidget(page))

        def finish_transition() -> None:
            current.setGraphicsEffect(None)
            page.setGraphicsEffect(None)
            if previous is not None:
                self.stack.removeWidget(previous)
                previous.deleteLater()
            self._transition_in_progress = False
            self._transition_group = None

        group.finished.connect(finish_transition)
        self._transition_group = group
        group.start()

    def _clear_dynamic_pages(self) -> None:
        if self._transition_group is not None:
            self._transition_group.stop()
        self._transition_group = None
        self._transition_in_progress = False
        self.stack.setCurrentWidget(self.home)
        self.app_header.set_home_mode(True)
        self.shell.set_home_background_active(True)
        for index in range(self.stack.count() - 1, -1, -1):
            page = self.stack.widget(index)
            if page is self.home:
                continue
            page.setGraphicsEffect(None)
            self.stack.removeWidget(page)
            page.deleteLater()
        self._dynamic_page = None

    def _show_home_now(self) -> None:
        self.active_exam_screen = None
        self.current_subject = None
        self.app_header.set_home_mode(True)
        self.shell.set_home_background_active(True)
        self._apply_theme(self.settings.theme)
        self._clear_dynamic_pages()
        self.refresh_data()

    def show_home(self) -> None:
        if self._resolve_active_exam_exit():
            self._show_home_now()

    def _ask_active_exam_exit(self) -> str:
        dialog = QMessageBox(self)
        dialog.setObjectName("activeExamExitDialog")
        dialog.setWindowTitle("Rời bài thi")
        dialog.setIcon(QMessageBox.Warning)
        dialog.setText("Bài thi đang làm sẽ không được lưu. Bạn muốn xử lý thế nào?")
        cancel_button = dialog.addButton("Cancel", QMessageBox.RejectRole)
        submit_button = dialog.addButton("Yes — Nộp và Thoát", QMessageBox.AcceptRole)
        discard_button = dialog.addButton(
            "No — Thoát và Không lưu", QMessageBox.DestructiveRole
        )
        cancel_button.setProperty("secondary", True)
        discard_button.setProperty("danger", True)
        dialog.setDefaultButton(cancel_button)
        dialog.setEscapeButton(cancel_button)
        dialog.exec_()
        clicked = dialog.clickedButton()
        if clicked is submit_button:
            return "submit"
        if clicked is discard_button:
            return "discard"
        return "cancel"

    def _resolve_active_exam_exit(self) -> bool:
        screen = self.active_exam_screen
        if screen is None or not screen.active:
            self.active_exam_screen = None
            return True
        screen.pause_countdown()
        action = self._ask_active_exam_exit()
        if action == "cancel":
            screen.resume_countdown()
            return False
        if action == "submit":
            screen.submit_exam("exit", emit_result=False)
        else:
            screen.discard_exam()
        self.active_exam_screen = None
        return True

    def refresh_data(self) -> None:
        if self._scan_running:
            self._rescan_requested = True
            return
        self._scan_running = True
        self.home.set_loading(self.data_dir)
        task = ScanTask(self.data_dir)
        task.signals.completed.connect(self._apply_scan_result)
        task.signals.failed.connect(self._scan_failed)
        self.thread_pool.start(task)

    def _apply_scan_result(self, scanned_dir: Path, subjects: list[Subject]) -> None:
        self._scan_running = False
        if Path(scanned_dir) != self.data_dir:
            self._rescan_requested = True
        else:
            self._apply_subjects(subjects)
        if self._rescan_requested:
            self._rescan_requested = False
            self.refresh_data()

    def _scan_failed(self, scanned_dir: Path, message: str) -> None:
        self._scan_running = False
        LOGGER.warning("Không quét được %s: %s", scanned_dir, message)
        self.home.notice.setText(f"Không thể quét dữ liệu: {message}")
        if self._rescan_requested:
            self._rescan_requested = False
            self.refresh_data()

    def _apply_subjects(self, subjects: list[Subject]) -> None:
        self.subjects = {subject.name: subject for subject in subjects}
        all_questions = [
            question for subject in subjects for question in subject.questions
        ]
        self.database.sync_questions(
            all_questions, [subject.name for subject in subjects]
        )
        bank_results = QuestionBankUpdateChecker(
            self.database, self.settings.crop_region
        ).check(subjects, apply=True)
        answer_repository = AnswerKeyRepository()
        self.answer_reports = {
            subject.name: answer_repository.load(subject.path, subject.questions)
            for subject in subjects
        }
        self.home.set_subjects(subjects, self.data_dir)
        self._notify_bank_updates(bank_results)
        self._reset_watch_paths(subjects)

    def _notify_bank_updates(self, results: list[BankUpdateResult]) -> None:
        messages = [
            f"{result.subject}\n{result.notification}"
            for result in results
            if result.applied and result.notification
        ]
        errors = [
            f"{result.subject}: " + "; ".join(result.errors)
            for result in results
            if result.errors
        ]
        if errors:
            LOGGER.warning("Question bank update chưa hoàn tất: %s", " | ".join(errors))
            self.home.notice.setText("Lỗi cập nhật đáp án: " + " | ".join(errors))
        if not messages:
            return
        dialog = QMessageBox(self)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.setWindowTitle("Bộ câu hỏi đã được cập nhật")
        dialog.setIcon(QMessageBox.Information)
        dialog.setText("\n\n".join(messages))
        dialog.setStandardButtons(QMessageBox.Ok)
        dialog.finished.connect(
            lambda _result, current=dialog: (
                self._bank_update_dialogs.remove(current)
                if current in self._bank_update_dialogs
                else None
            )
        )
        self._bank_update_dialogs.append(dialog)
        dialog.show()

    def _reset_watch_paths(self, subjects: list[Subject]) -> None:
        old_paths = self.watcher.directories() + self.watcher.files()
        if old_paths:
            self.watcher.removePaths(old_paths)
        paths: list[str] = []
        if self.data_dir.exists():
            paths.append(str(self.data_dir))
        for subject in subjects:
            paths.append(str(subject.path))
            paths.extend(str(path) for path in subject.path.iterdir() if path.is_dir())
            csv_path = subject.path / AnswerKeyRepository.FILE_NAME
            if csv_path.exists():
                paths.append(str(csv_path))
            pending_path = subject.path / PENDING_ANSWERS_FILE
            if pending_path.exists():
                paths.append(str(pending_path))
        if paths:
            missing = self.watcher.addPaths(paths)
            if missing:
                LOGGER.debug("Không theo dõi được một số đường dẫn: %s", missing)

    def _schedule_refresh(self, _path: str) -> None:
        self.refresh_timer.start()

    def show_modes(self, subject_name: str) -> None:
        subject = self.subjects.get(subject_name)
        if subject is None:
            QMessageBox.warning(
                self, "Môn học không tồn tại", "Hãy bấm Làm mới và thử lại."
            )
            return
        self.current_subject = subject
        report = self.answer_reports[subject.name]
        review_service = AdaptiveReviewService(
            self.database,
            subject.questions,
            report.answers,
        )
        page = ModeScreen(
            subject,
            report,
            self.database.card_stats(subject.name),
            review_service.top_errors_by_category(),
            self.settings.crop_region,
            learning_questions=review_service.learning_by_category(),
        )
        page.back_requested.connect(self.show_home)
        page.mode_selected.connect(self._open_mode)
        page.learning_status_changed.connect(self.database.rate_card)
        self._set_dynamic_page(page)

    def _open_mode(self, mode: str) -> None:
        if self.current_subject is None or self._transition_in_progress:
            return
        subject = self.current_subject
        if mode == "flash":
            report = self.answer_reports[subject.name]
            page = FlashcardScreen(
                FlashcardService(self.database, subject.questions, report.answers),
                self.settings.crop_region,
            )
            page.back_requested.connect(lambda: self.show_modes(subject.name))
            self._set_dynamic_page(page, animate=True)
        elif mode == "cram":
            report = self.answer_reports[subject.name]
            if report.valid_count == 0:
                QMessageBox.warning(
                    self,
                    "Chưa có đáp án hợp lệ",
                    f"Cramming tự chấm cần answers.csv. Không có câu hợp lệ tại:\n"
                    f"{report.csv_path}",
                )
                return
            page = CrammingScreen(
                CrammingService(self.database, subject.questions, report.answers),
                self.settings.crop_region,
            )
            page.back_requested.connect(lambda: self.show_modes(subject.name))
            self._set_dynamic_page(page, animate=True)
        elif mode == "exam":
            self.show_exam_config(animate=True)

    def _exam_service(self) -> ExamService:
        if self.current_subject is None:
            raise RuntimeError("Chưa chọn môn học")
        report = self.answer_reports[self.current_subject.name]
        return ExamService(
            self.database, self.current_subject.questions, report.answers
        )

    def show_exam_config(self, animate: bool = False) -> None:
        if self.current_subject is None:
            return
        subject = self.current_subject
        page = ExamConfigScreen(
            subject, self._exam_service(), self.answer_reports[subject.name]
        )
        page.back_requested.connect(lambda: self.show_modes(subject.name))
        page.exam_requested.connect(self.start_exam)
        self._set_dynamic_page(page, animate=animate)

    def start_exam(self, session: ExamSession) -> None:
        page = ExamScreen(session, self.settings.crop_region)
        self.active_exam_screen = page
        page.back_requested.connect(self._leave_exam)
        page.result_ready.connect(self.show_result)
        self._set_dynamic_page(page)

    def _leave_exam(self) -> None:
        if self._resolve_active_exam_exit():
            self.show_exam_config()

    def show_result(self, result: ExamResult) -> None:
        self.active_exam_screen = None
        page = ResultScreen(result, self.settings.crop_region)
        page.home_requested.connect(self.show_home)
        page.back_requested.connect(self.show_home)
        page.retest_requested.connect(
            lambda choice: self._handle_retest(choice, result.config)
        )
        self._set_dynamic_page(page)

    def _handle_retest(self, choice: str, config: ExamConfig) -> None:
        subject = self.subjects.get(config.subject)
        if subject is None:
            QMessageBox.warning(
                self,
                "Không tìm thấy môn học",
                f"Môn {config.subject} không còn trong thư mục DATA. Hãy làm mới dữ liệu.",
            )
            self.show_home()
            return
        self.current_subject = subject
        if choice == "new_config":
            self.show_exam_config()
            return
        if choice != "same_config":
            return
        try:
            session = self._exam_service().create_session(config)
        except ValueError as exc:
            QMessageBox.warning(
                self,
                "Không thể làm lại đề",
                f"Cấu hình cũ không còn phù hợp với dữ liệu hiện tại:\n{exc}",
            )
            self.show_exam_config()
            return
        self.start_exam(session)

    def _apply_theme(self, theme_name: str) -> None:
        self.theme_manager.apply(theme_name)
        if hasattr(self, "app_header"):
            self.app_header.update_theme()
        if hasattr(self, "home"):
            self.home.update_theme()
        if self._dynamic_page is not None and hasattr(
            self._dynamic_page, "update_theme"
        ):
            self._dynamic_page.update_theme()

    def show_settings(self) -> None:
        # Tìm đường dẫn ảnh câu hỏi hợp lệ đầu tiên từ các môn học (sắp xếp tên môn cố định)
        preview_path = next(
            (
                question.absolute_path
                for subject in sorted(self.subjects.values(), key=lambda s: s.name)
                for question in subject.questions
                if question.absolute_path and question.absolute_path.is_file()
            ),
            None,
        )
        valid = sum(report.valid_count for report in self.answer_reports.values())
        missing = sum(len(report.missing) for report in self.answer_reports.values())
        invalid = sum(len(report.invalid) for report in self.answer_reports.values())
        status = f"{valid} hợp lệ • {missing} thiếu • {invalid} lỗi định dạng"
        page = SettingsScreen(self.settings, preview_path, status)
        page.back_requested.connect(self._cancel_settings)
        page.theme_preview_requested.connect(self._apply_theme)
        page.saved.connect(self._save_settings)
        self._set_dynamic_page(page)

    def _cancel_settings(self) -> None:
        self._apply_theme(self.settings.theme)
        self.show_home()

    def _save_settings(self, settings: AppSettings) -> None:
        path = Path(settings.data_dir).expanduser()
        settings.data_dir = str(path.resolve())
        self.settings = settings
        self.data_dir = Path(settings.data_dir)
        self.database.save_app_settings(settings)
        QMessageBox.information(self, "Đã lưu", "Cài đặt đã được lưu.")
        self.show_home()

    def show_history(self) -> None:
        history = [dict(attempt) for attempt in self.database.exam_history()]
        page = HistoryScreen(history)
        page.back_requested.connect(self.show_home)
        page.delete_requested.connect(self._delete_exam_attempts)
        self._set_dynamic_page(page)

    def _delete_exam_attempts(self, attempt_ids: list[int]) -> None:
        if not attempt_ids:
            return
        response = QMessageBox.question(
            self,
            "Xóa lịch sử bài thi",
            "Bạn có chắc chắn muốn xóa (các) bài thi đã chọn? "
            "Dữ liệu này sẽ không thể khôi phục.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if response != QMessageBox.Yes:
            return
        self.database.delete_exam_attempts(attempt_ids)
        self.show_history()

    def closeEvent(self, event) -> None:
        if not self._resolve_active_exam_exit():
            event.ignore()
            return
        if hasattr(self, "watcher"):
            try:
                dirs = self.watcher.directories()
                if dirs:
                    self.watcher.removePaths(dirs)
                files = self.watcher.files()
                if files:
                    self.watcher.removePaths(files)
            except RuntimeError as exc:
                LOGGER.debug(
                    "File watcher was already disposed during shutdown: %s", exc
                )
        if hasattr(self, "thread_pool"):
            self.thread_pool.clear()
            self.thread_pool.waitForDone(1500)
        geometry = self.saveGeometry().toHex().data().decode("ascii")
        self.database.set_setting("window_geometry", geometry)
        super().closeEvent(event)
