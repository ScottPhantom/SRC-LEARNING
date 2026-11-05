"""Three SRC LEARNING modes rendered inside a Colab notebook output cell."""

from __future__ import annotations

import html
import io
import threading
import time
from pathlib import Path

import ipywidgets as widgets
from IPython.display import display
from PIL import Image

from app.config import CATEGORY_LABELS, DEFAULT_MASK_REGION
from app.domain.models import ExamConfig, FeedbackMode, Question
from app.services.exam import ExamResult, ExamService, ExamSession
from app.services.study import CrammingService, FlashcardService
from colab_mobile.session import MobileLearningSession


def question_image(path: Path) -> bytes:
    """Crop the answer strip exactly as the desktop image viewer does."""
    with Image.open(path) as original:
        image = original.convert("RGB")
        bottom = (
            max(1, min(image.height, round(image.height * DEFAULT_MASK_REGION[1])))
            if DEFAULT_MASK_REGION[3] > 0 else image.height
        )
        image = image.crop((0, 0, image.width, bottom))
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


class NotebookLearningUI:
    """Small mobile layout using only core Jupyter widgets, with no web server."""

    def __init__(self, session: MobileLearningSession | None = None) -> None:
        self.session = session or MobileLearningSession()
        self.flash: FlashcardService | None = None
        self.cram: CrammingService | None = None
        self.exam: ExamSession | None = None
        self.exam_result: ExamResult | None = None
        self.exam_deadline = 0.0
        self._exam_timer: threading.Timer | None = None
        self._exam_lock = threading.RLock()

        self.code = widgets.Text(description="Drive ID", placeholder="ID hoặc link chia sẻ", layout=widgets.Layout(width="100%"))
        self.install = widgets.Button(description="Tải môn", button_style="primary")
        self.notice = widgets.HTML()
        self.subject = widgets.Dropdown(description="Môn", options=[], layout=widgets.Layout(width="100%"))
        self.mode = widgets.Dropdown(
            description="Chế độ",
            options=[("Flash Cards", "flash"), ("Học cấp tốc", "cram"), ("Mock Exam", "exam")],
            layout=widgets.Layout(width="100%"),
        )
        self.body = widgets.VBox(layout=widgets.Layout(width="100%"))
        self.root = widgets.VBox(
            [
                widgets.HTML("<h2>SRC LEARNING · Colab</h2><p>Mỗi lần chạy notebook là một phiên mới.</p>"),
                self.code, self.install, self.notice, self.subject, self.mode, self.body,
            ],
            layout=widgets.Layout(width="100%", max_width="960px"),
        )
        self.install.on_click(self._install_subject)
        self.subject.observe(self._change_subject, names="value")
        self.mode.observe(self._change_mode, names="value")
        self._render()

    def display(self) -> None:
        display(self.root)

    def _message(self, value: str, *, error: bool = False) -> None:
        color = "#b42318" if error else "#175cd3"
        self.notice.value = f'<p style="color:{color}">{html.escape(value)}</p>'

    def _install_subject(self, _button: widgets.Button) -> None:
        code = self.code.value.strip()
        if not code:
            self._message("Hãy nhập Google Drive File ID hoặc link chia sẻ.", error=True)
            return
        self.install.disabled = True
        try:
            result = self.session.install_subject(
                code,
                progress=lambda _stage, percent, message: self._message(f"{percent}% · {message}"),
            )
            self.subject.options = sorted(self.session.subjects)
            self.subject.value = result.subject
            self._message(f"Đã cài {result.subject}: {result.question_count} câu.")
            self._render()
        except Exception as exc:
            self._message(str(exc), error=True)
        finally:
            self.install.disabled = False

    def _change_subject(self, change: dict) -> None:
        if change["new"] != change["old"]:
            self.flash = None
            self.cram = None
            self.exam = None
            self.exam_result = None
            self._cancel_timer()
            self._render()

    def _change_mode(self, _change: dict) -> None:
        self._render()

    def _current(self):
        name = self.subject.value
        return self.session.subjects.get(name), self.session.answer_reports.get(name)

    def _image(self, question: Question) -> widgets.Image:
        return widgets.Image(
            value=question_image(question.absolute_path),
            format="png",
            layout=widgets.Layout(width="100%", max_width="900px"),
        )

    def _render(self) -> None:
        subject, report = self._current()
        if subject is None or report is None:
            self.body.children = (widgets.HTML("Nhập Drive ID đã được phê duyệt để tải môn học."),)
        elif self.mode.value == "flash":
            self._render_flash(subject, report.answers)
        elif self.mode.value == "cram":
            self._render_cram(subject, report.answers)
        else:
            self._render_exam(subject, report.answers)

    def _render_flash(self, subject, answers) -> None:
        if self.flash is None:
            self.flash = FlashcardService(self.session.database, subject.questions, answers)
            self.flash.resume_or_start()
        state = self.flash.state()
        stats = self.flash.stats()
        summary = widgets.HTML(
            f"<b>Flash Cards</b> · Đã thuộc: {stats['known']} · Chưa thuộc: {stats['learning']}"
        )
        restart = widgets.Button(description="Học lại tất cả")
        restart.on_click(lambda _: (self.flash.restart(), self._render()))
        review = widgets.Button(description="Ôn câu chưa thuộc", disabled=stats["learning"] == 0)

        def start_review(_):
            try:
                self.flash.start_new(only_learning=True)
                self._render()
            except ValueError as exc:
                self._message(str(exc), error=True)

        review.on_click(start_review)
        if state.completed or state.question is None:
            self.body.children = (summary, widgets.HTML("Đã hết thẻ trong phiên này."), restart, review)
            return
        answer = widgets.HTML()
        reveal = widgets.Button(description="Hiện đáp án")
        reveal.on_click(lambda _: setattr(answer, "value", f"<b>Đáp án: {html.escape(state.question.correct_answer or 'Chưa có')}</b>"))
        known = widgets.Button(description="Đã thuộc", button_style="success")
        learning = widgets.Button(description="Chưa thuộc", button_style="warning")
        known.on_click(lambda _: (self.flash.rate_current(True), self._render()))
        learning.on_click(lambda _: (self.flash.rate_current(False), self._render()))
        self.body.children = (
            summary, widgets.HTML(f"Thẻ {state.position + 1}/{state.total}"),
            self._image(state.question), answer,
            widgets.HBox([reveal, known, learning], layout=widgets.Layout(flex_flow="row wrap")),
            widgets.HBox([restart, review], layout=widgets.Layout(flex_flow="row wrap")),
        )

    @staticmethod
    def _answer_input(question: Question):
        if question.is_multiple:
            return widgets.SelectMultiple(
                options=question.options, description="Đáp án", rows=len(question.options),
                layout=widgets.Layout(width="100%"),
            )
        return widgets.RadioButtons(
            options=[("Chưa chọn", ""), *[(letter, letter) for letter in question.options]],
            description="Đáp án", layout=widgets.Layout(width="100%"),
        )

    @staticmethod
    def _selected_answer(control) -> str:
        value = control.value
        return "".join(value) if isinstance(value, tuple) else value

    def _render_cram(self, subject, answers) -> None:
        if self.cram is None:
            self.cram = CrammingService(self.session.database, subject.questions, answers)
            if not self.cram.questions:
                self.body.children = (widgets.HTML("Học cấp tốc cần câu hỏi có đáp án hợp lệ."),)
                return
            self.cram.resume_or_start()
        state = self.cram.state()
        restart = widgets.Button(description="Bắt đầu vòng mới")
        restart.on_click(lambda _: (self.cram.start_new(), self._render()))
        if state.completed or state.question is None:
            self.body.children = (
                widgets.HTML(f"<b>Hoàn thành Học cấp tốc.</b> Đã thuộc: {state.mastered}; trả lời sai: {state.wrong}."),
                restart,
            )
            return
        control = self._answer_input(state.question)
        feedback = widgets.HTML()
        check = widgets.Button(description="Kiểm tra", button_style="primary")
        next_button = widgets.Button(description="Câu tiếp", disabled=True)

        def check_answer(_):
            selected = self._selected_answer(control)
            if not selected:
                self._message("Hãy chọn đáp án.", error=True)
                return
            correct = self.cram.is_answer_correct(state.question, selected)
            feedback.value = (
                f"<b>{'Đúng' if correct else 'Sai'}.</b> "
                f"Đáp án: {html.escape(state.question.correct_answer)}"
            )
            check.disabled = True
            control.disabled = True
            next_button.disabled = False
            next_button.on_click(lambda _button: (self.cram.rate_current(correct), self._render()))

        check.on_click(check_answer)
        self.body.children = (
            widgets.HTML(
                f"<b>Học cấp tốc</b> · Vòng {state.current_round}/{state.total_rounds} "
                f"· Còn {state.remaining} · Đã thuộc {state.mastered}"
            ),
            self._image(state.question), control, feedback,
            widgets.HBox([check, next_button, restart], layout=widgets.Layout(flex_flow="row wrap")),
        )

    def _render_exam(self, subject, answers) -> None:
        if self.exam_result is not None:
            self._render_exam_result()
        elif self.exam is not None and not self.exam.submitted:
            self._render_exam_question()
        else:
            self._render_exam_setup(subject, answers)

    def _render_exam_setup(self, subject, answers) -> None:
        service = ExamService(self.session.database, subject.questions, answers)
        eligible = service.eligible_questions(tuple(CATEGORY_LABELS))
        if not eligible:
            self.body.children = (widgets.HTML("Mock Exam cần câu hỏi có đáp án hợp lệ."),)
            return
        categories = widgets.SelectMultiple(
            options=[(CATEGORY_LABELS[key], key) for key in CATEGORY_LABELS],
            value=tuple({q.category for q in eligible}),
            description="Nhóm", rows=4, layout=widgets.Layout(width="100%"),
        )
        count = widgets.BoundedIntText(value=min(10, len(eligible)), min=1, max=len(eligible), description="Số câu")
        duration = widgets.BoundedIntText(value=30, min=1, max=180, description="Phút")
        feedback = widgets.Dropdown(
            options=[("Chấm sau khi nộp", FeedbackMode.DEFERRED), ("Chấm từng câu", FeedbackMode.IMMEDIATE)],
            description="Chấm", layout=widgets.Layout(width="100%"),
        )
        start = widgets.Button(description="Bắt đầu thi", button_style="primary")
        history = widgets.Button(description="Lịch sử bài thi")
        history_output = widgets.HTML()

        def update_count(_change):
            available = len(service.eligible_questions(categories.value))
            count.max = max(1, available)
            count.value = min(count.value, count.max)

        categories.observe(update_count, names="value")

        def begin(_):
            try:
                config = ExamConfig(
                    subject=subject.name,
                    categories=tuple(categories.value),
                    question_count=count.value,
                    duration_minutes=duration.value,
                    feedback_mode=feedback.value,
                )
                self.exam = service.create_session(config)
                self.exam_result = None
                self.subject.disabled = True
                self.exam_deadline = time.monotonic() + 60 * config.duration_minutes
                self._cancel_timer()
                self._exam_timer = threading.Timer(60 * config.duration_minutes, self._submit_exam, args=("time",))
                self._exam_timer.daemon = True
                self._exam_timer.start()
                self._render()
            except ValueError as exc:
                self._message(str(exc), error=True)

        def show_history(_):
            rows = self.session.database.exam_history(subject.name)
            if not rows:
                history_output.value = "Chưa có bài thi trong phiên Colab này."
            else:
                history_output.value = "<br>".join(
                    f"#{row['id']}: {row['score']}/10 · {row['correct']}/{row['total']} câu đúng"
                    for row in rows[:10]
                )

        start.on_click(begin)
        history.on_click(show_history)
        self.body.children = (
            widgets.HTML(f"<b>Mock Exam</b> · {len(eligible)} câu đủ đáp án"),
            categories, count, duration, feedback,
            widgets.HBox([start, history], layout=widgets.Layout(flex_flow="row wrap")), history_output,
        )

    def _exam_expired(self) -> bool:
        if time.monotonic() >= self.exam_deadline:
            self._submit_exam("time")
            return True
        return False

    def _render_exam_question(self) -> None:
        if self._exam_expired():
            return
        exam = self.exam
        item = exam.current
        control = self._answer_input(item.question)
        control.value = tuple(item.selected_answer) if item.question.is_multiple else item.selected_answer
        control.disabled = item.confirmed
        status = widgets.HTML(
            f"<b>Đáp án: {html.escape(item.question.correct_answer)}</b>"
            if item.confirmed else ""
        )
        previous = widgets.Button(description="← Trước", disabled=exam.current_index == 0)
        following = widgets.Button(description="Tiếp →", disabled=exam.current_index == len(exam.items) - 1)
        submit = widgets.Button(description="Nộp bài", button_style="danger")
        check = widgets.Button(description="Chấm câu", disabled=item.confirmed)

        def save() -> bool:
            if self._exam_expired():
                return False
            if not item.confirmed:
                exam.set_answer(self._selected_answer(control))
            return True

        def move(offset: int):
            if save():
                exam.current_index += offset
                self._render()

        def check_current(_):
            try:
                if save():
                    correct = exam.confirm_current()
                    status.value = (
                        f"<b>{'Đúng' if correct else 'Sai'}.</b> "
                        f"Đáp án: {html.escape(item.question.correct_answer)}"
                    )
                    control.disabled = True
                    check.disabled = True
            except ValueError as exc:
                self._message(str(exc), error=True)

        previous.on_click(lambda _: move(-1))
        following.on_click(lambda _: move(1))
        submit.on_click(lambda _: self._submit_exam("user") if save() else None)
        check.on_click(check_current)
        remaining = max(0, round((self.exam_deadline - time.monotonic()) / 60, 1))
        controls = [previous, following, submit]
        if exam.config.feedback_mode == FeedbackMode.IMMEDIATE:
            controls.insert(2, check)
        self.body.children = (
            widgets.HTML(
                f"<b>Mock Exam</b> · Câu {exam.current_index + 1}/{len(exam.items)} "
                f"· Còn khoảng {remaining} phút"
            ),
            self._image(item.question), control, status,
            widgets.HBox(controls, layout=widgets.Layout(flex_flow="row wrap")),
        )

    def _submit_exam(self, reason: str) -> None:
        with self._exam_lock:
            if self.exam is None or self.exam.submitted:
                return
            self.exam_result = self.exam.submit(reason)
            self._cancel_timer()
            self.subject.disabled = False
            if self.mode.value == "exam":
                self._render_exam_result()

    def _render_exam_result(self) -> None:
        result = self.exam_result
        details = "<br>".join(
            f"Câu {index}: chọn {html.escape(item.selected_answer or '—')} · "
            f"đúng {html.escape(item.question.correct_answer)} · {item.awarded_score:.2f} điểm"
            for index, item in enumerate(result.items, 1)
        )
        again = widgets.Button(description="Thi bài mới", button_style="primary")

        def restart(_):
            self.exam = None
            self.exam_result = None
            self._render()

        again.on_click(restart)
        self.body.children = (
            widgets.HTML(
                f"<h3>Kết quả: {result.score}/10 · {result.status}</h3>"
                f"<p>Đúng {result.correct}/{result.total}; bỏ trống {result.unanswered}.</p>"
                f"<p>{details}</p>"
            ),
            again,
        )

    def _cancel_timer(self) -> None:
        if self._exam_timer is not None:
            self._exam_timer.cancel()
            self._exam_timer = None

    def close(self) -> None:
        with self._exam_lock:
            self._cancel_timer()
            self.session.close()
