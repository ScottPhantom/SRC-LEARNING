"""Touch-friendly Gradio interface for a fresh SRC Learning Colab runtime."""

from __future__ import annotations

import html
import os
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import gradio as gr
from PIL import Image

from app.config import CATEGORY_LABELS
from app.domain.models import ExamConfig, FeedbackMode, Question, normalize_answer
from app.services.adaptive import AdaptiveReviewService
from app.services.exam import ExamService
from app.services.study import CrammingService, FlashcardService
from colab_mobile.image import question_image
from colab_mobile.session import MobileLearningSession


@dataclass
class ViewState:
    page: str = "home"
    subject_name: str = ""
    flash: FlashcardService | None = None
    flash_history: list[tuple[Question, bool]] = field(default_factory=list)
    flash_cursor: int | None = None
    revealed: bool = False
    cram: CrammingService | None = None
    cram_history: list[tuple[Question, str, bool]] = field(default_factory=list)
    cram_cursor: int | None = None
    cram_pending: tuple | None = None
    selection: str = ""
    quick_entries: list | None = None
    quick_index: int = 0
    quick_ratable: bool = False
    exam: object | None = None
    exam_result: object | None = None
    exam_deadline: float = 0.0
    confirm_submit: bool = False
    feedback: FeedbackMode = FeedbackMode.DEFERRED
    notice: str = ""


_views: dict[str, ViewState] = {}
_session: MobileLearningSession | None = None


def learning_session() -> MobileLearningSession:
    global _session
    if _session is None:
        root = os.environ.get("SRC_LEARNING_SESSION_ROOT")
        _session = MobileLearningSession(Path(root) if root else None)
        _session.refresh_subjects()
    return _session


def view_for(session_hash: str | None) -> ViewState:
    return _views.setdefault(session_hash or "local", ViewState())


def current(view: ViewState):
    session = learning_session()
    return session.subjects.get(view.subject_name), session.answer_reports.get(view.subject_name)


def reset_modes(view: ViewState) -> None:
    view.flash = None
    view.flash_history = []
    view.flash_cursor = None
    view.revealed = False
    view.cram = None
    view.cram_history = []
    view.cram_cursor = None
    view.cram_pending = None
    view.selection = ""
    view.quick_entries = None
    view.exam = None
    view.exam_result = None
    view.confirm_submit = False


def picture(question: Question) -> Image.Image:
    with Image.open(BytesIO(question_image(question.absolute_path))) as source:
        return source.copy()


def question_panel(question: Question) -> None:
    gr.Image(
        value=picture(question),
        show_label=False,
        buttons=["fullscreen"],
        interactive=False,
        elem_classes="src-question-image",
    )


def heading(title: str, subtitle: str = "") -> None:
    gr.HTML(f'<h1>{html.escape(title)}</h1><p class="src-muted">{html.escape(subtitle)}</p>')


def badge(text: str) -> None:
    gr.HTML(f'<span class="src-pill">{html.escape(text)}</span>')


def icon(name: str, *, css_class: str = "") -> str:
    return f'<morph-icon data-src-icon="{name}" class="{css_class}" aria-hidden="true"></morph-icon>'


def create_app() -> gr.Blocks:
    session = learning_session()
    with gr.Blocks(title="SRC Learning", fill_width=True) as demo:
        revision = gr.State(0)
        tick = gr.Timer(1)

        @gr.render(inputs=revision, triggers=[demo.load, revision.change])
        def screen(version: int, request: gr.Request):
            view = view_for(request.session_hash)
            listener_index = 0

            def bind(button: gr.Button, fn, inputs: list | None = None, with_progress: bool = False) -> None:
                nonlocal listener_index
                extra = inputs or []
                listener_key = f"{view.page}:{listener_index}"
                listener_index += 1

                def run(_revision, *values, progress=gr.Progress()):
                    try:
                        if with_progress:
                            fn(*values, progress=progress)
                        else:
                            fn(*values)
                    except Exception as exc:
                        view.notice = str(exc)
                    return _revision + 1

                button.click(run, inputs=[revision, *extra], outputs=revision, key=listener_key)

            def navigate(page: str) -> None:
                view.page = page
                view.notice = ""

            with gr.Row(elem_classes="src-toolbar"):
                gr.HTML('<div class="src-logo"><span class="src-logo-mark">✦</span><strong>SRC Learning</strong></div>', scale=6)
                toolbar = [
                    ("Plus", "Thêm môn", "add"),
                    ("History", "Lịch sử bài thi", "history"),
                    ("RotateCw", "Quét lại thư viện", "refresh"),
                    ("Settings", "Cài đặt", "settings"),
                ]
                for symbol, label, page in toolbar:
                    button = gr.Button(label, elem_classes=["src-icon-button", f"src-icon-{symbol}"],
                                       interactive=page != "add" or view.exam is None, min_width=64,
                                       scale=0)
                    if page == "refresh":
                        bind(button, session.refresh_subjects)
                    else:
                        bind(button, lambda target=page: navigate(target))
            gr.HTML('<div class="src-divider"></div>')

            if view.page != "home":
                target = "home" if view.page in {"add", "modes", "settings"} or not view.subject_name else "modes"
                back = gr.Button("Quay lại", elem_classes="src-back src-icon-ArrowLeft", scale=0)
                bind(back, lambda: navigate(target))
            if view.notice:
                gr.HTML(f'<div class="src-notice">{html.escape(view.notice)}</div>')

            subject, report = current(view)
            if view.page == "home":
                heading("Thư viện", "Chọn môn học để bắt đầu ôn tập")
                if view.exam is not None:
                    badge("Bài thi đang làm vẫn tiếp tục tính giờ")
                    resume = gr.Button("Tiếp tục bài thi", variant="primary")
                    bind(resume, lambda: navigate("exam"))
                if not session.subjects:
                    gr.HTML('<div class="src-panel">Thư viện trống. Nhập Drive ID của môn để tải dữ liệu.</div>')
                    add = gr.Button("Thêm môn học", variant="primary", elem_classes="src-icon-Plus")
                    bind(add, lambda: navigate("add"))
                for name, item in sorted(session.subjects.items()):
                    with gr.Row(elem_classes="src-panel src-subject-row"):
                        gr.HTML(f'<div class="src-monogram">{html.escape(name[:3].upper())}</div>')
                        gr.HTML(f'<div><h2>{html.escape(name)}</h2><p class="src-muted">{item.question_count} câu hỏi · {len(item.category_counts)} loại câu</p></div>', scale=5)
                        open_button = gr.Button("Mở môn học", variant="primary", elem_classes="src-icon-ArrowRight", interactive=view.exam is None)

                        def open_subject(selected=name):
                            view.subject_name = selected
                            reset_modes(view)
                            navigate("modes")

                        bind(open_button, open_subject)

            elif view.page == "add":
                heading("Thêm môn học", "Nhập Google Drive File ID hoặc link chia sẻ của gói trong danh mục SRC Learning.")
                code = gr.Textbox(label="Drive ID hoặc link chia sẻ", placeholder="Dán ID môn học", interactive=True)
                download = gr.Button("Tải môn học", variant="primary", elem_classes="src-icon-Plus")

                def install(value: str, progress=gr.Progress()):
                    if not value.strip():
                        raise ValueError("Hãy nhập Drive ID của môn học.")
                    result = session.install_subject(value.strip(), lambda _step, percent, message: progress(percent / 100, desc=message))
                    view.subject_name = result.subject
                    reset_modes(view)
                    view.page = "modes"
                    view.notice = f"Đã tải {result.subject}: {result.question_count} câu hỏi."

                bind(download, install, [code], with_progress=True)

            elif view.page == "modes" and subject and report:
                heading(subject.name, f"{subject.question_count} câu hỏi · {report.valid_count} câu có đáp án")
                if view.exam is not None:
                    badge("Bài thi đang làm vẫn tiếp tục tính giờ")
                    resume = gr.Button("Tiếp tục bài thi", variant="primary")
                    bind(resume, lambda: navigate("exam"))
                else:
                    modes = [
                        ("flash", "BookOpen", "Học bình thường", "Lật thẻ, tự đánh giá đã thuộc hoặc chưa thuộc."),
                        ("cram", "Zap", "Học cấp tốc", "Trả lời theo vòng, ôn lại câu sai."),
                        ("exam", "ClipboardList", "Tạo bộ đề thi", "Chọn số câu, thời gian và cách chấm."),
                    ]
                    with gr.Row(elem_classes="src-mode-row"):
                        for page, symbol, title, description in modes:
                            with gr.Column(elem_classes="src-panel src-mode-card", min_width=220):
                                gr.HTML(f'<div class="src-mode-icon">{icon(symbol)}</div><h2>{title}</h2><p>{description}</p>')
                                button = gr.Button("Bắt đầu", variant="primary", elem_classes="src-icon-ArrowRight")
                                bind(button, lambda target=page: navigate(target))
                    stats = session.database.card_stats(subject.name)
                    heading("Tiến độ học tập")
                    gr.HTML(f'<div class="src-stats"><div>Đã thuộc<strong>{stats["known"]}</strong></div><div>Chưa thuộc<strong>{stats["learning"]}</strong></div><div>Tổng câu<strong>{subject.question_count}</strong></div></div>')
                    heading("Ôn tập nhanh")
                    adaptive = AdaptiveReviewService(session.database, subject.questions, report.answers)
                    learning = [entry for group in adaptive.learning_by_category().values() for entry in group]
                    weak = [entry for group in adaptive.top_errors_by_category().values() for entry in group]
                    with gr.Row():
                        for entries, label, ratable in ((learning, "Ôn câu mới/chưa thuộc", True), (weak, "Ôn câu sai nhiều", False)):
                            button = gr.Button(f"{label} ({len(entries)})", interactive=bool(entries))

                            def start_quick(items=entries, can_rate=ratable):
                                view.quick_entries = list(items)
                                view.quick_index = 0
                                view.quick_ratable = can_rate
                                view.page = "quick"

                            bind(button, start_quick)

            elif view.page == "flash" and subject and report:
                if view.flash is None:
                    view.flash = FlashcardService(session.database, subject.questions, report.answers)
                    view.flash.resume_or_start()
                card = view.flash.state()
                stats = view.flash.stats()
                heading("Flash Cards", f"{subject.name} · Đã thuộc {stats['known']} · Chưa thuộc {stats['learning']}")
                if view.flash_cursor is not None:
                    old, known = view.flash_history[view.flash_cursor]
                    badge(f"Xem lại {view.flash_cursor + 1}/{len(view.flash_history)} · {'Đã thuộc' if known else 'Chưa thuộc'} · Chỉ xem")
                    with gr.Row(elem_classes="src-question-row"):
                        with gr.Column(scale=3, min_width=300):
                            question_panel(old)
                        with gr.Column(scale=1, min_width=230, elem_classes="src-panel"):
                            heading("Đáp án", old.correct_answer or "Chưa có")
                    with gr.Row():
                        previous = gr.Button("Câu trước", interactive=view.flash_cursor > 0, elem_classes="src-icon-ArrowLeft")
                        next_button = gr.Button("Câu sau", elem_classes="src-icon-ArrowRight")
                    bind(previous, lambda: setattr(view, "flash_cursor", view.flash_cursor - 1))
                    bind(next_button, lambda: setattr(view, "flash_cursor", None if view.flash_cursor == len(view.flash_history) - 1 else view.flash_cursor + 1))
                elif card.completed or card.question is None:
                    badge("Đã hết thẻ trong phiên này")
                    restart = gr.Button("Học lại tất cả", variant="primary", elem_classes="src-icon-RotateCcw")
                    bind(restart, lambda: (view.flash.restart(), view.flash_history.clear(), setattr(view, "revealed", False)))
                else:
                    badge(f"Thẻ {card.position + 1}/{card.total}")
                    with gr.Row(elem_classes="src-question-row"):
                        with gr.Column(scale=3, min_width=300):
                            question_panel(card.question)
                        with gr.Column(scale=1, min_width=230, elem_classes="src-panel"):
                            badge("FLASH CARDS")
                            heading(f"Câu {card.position + 1}", CATEGORY_LABELS.get(card.question.category, card.question.category))
                            gr.HTML(f'<strong class="src-answer">Đáp án: {html.escape(card.question.correct_answer or "Chưa có")}</strong>' if view.revealed else '<p class="src-muted">Xem câu hỏi rồi hiện đáp án để tự đánh giá.</p>')
                    with gr.Row():
                        restart = gr.Button("Học lại", elem_classes="src-icon-RotateCcw")
                        only_learning = gr.Button("Chỉ học Chưa thuộc")
                        reveal = gr.Button("Hiện đáp án", variant="primary", elem_classes="src-icon-Eye")
                        wrong = gr.Button("Chưa thuộc", interactive=view.revealed)
                        known = gr.Button("Đã thuộc", interactive=view.revealed)
                    bind(restart, lambda: (view.flash.restart(), view.flash_history.clear(), setattr(view, "revealed", False)))
                    bind(only_learning, lambda: (view.flash.start_new(True), view.flash_history.clear(), setattr(view, "revealed", False)))
                    bind(reveal, lambda: setattr(view, "revealed", True))

                    def rate(value: bool):
                        view.flash_history.append((card.question, value))
                        view.flash.rate_current(value)
                        view.revealed = False

                    bind(wrong, lambda: rate(False))
                    bind(known, lambda: rate(True))
                    with gr.Row():
                        previous = gr.Button("Câu trước", interactive=bool(view.flash_history), elem_classes="src-icon-ArrowLeft")
                        skip = gr.Button("Bỏ qua / Câu sau", elem_classes="src-icon-ArrowRight")
                    bind(previous, lambda: setattr(view, "flash_cursor", len(view.flash_history) - 1))
                    bind(skip, lambda: rate(False))

            elif view.page == "quick" and view.quick_entries:
                entry = view.quick_entries[view.quick_index]
                heading("Ôn tập nhanh", f"Câu {view.quick_index + 1}/{len(view.quick_entries)}")
                with gr.Row(elem_classes="src-question-row"):
                    with gr.Column(scale=3, min_width=300):
                        question_panel(entry.question)
                    with gr.Column(scale=1, min_width=230, elem_classes="src-panel"):
                        heading("Đáp án", entry.correct_answer or "Chưa có")
                        badge(CATEGORY_LABELS.get(entry.question.category, entry.question.category))
                with gr.Row():
                    previous = gr.Button("Trước", interactive=view.quick_index > 0, elem_classes="src-icon-ArrowLeft")
                    following = gr.Button("Tiếp", interactive=view.quick_index < len(view.quick_entries) - 1, elem_classes="src-icon-ArrowRight")
                    bind(previous, lambda: setattr(view, "quick_index", view.quick_index - 1))
                    bind(following, lambda: setattr(view, "quick_index", view.quick_index + 1))
                    if view.quick_ratable:
                        for label, known in (("Chưa thuộc", False), ("Đã thuộc", True)):
                            button = gr.Button(label)

                            def rate_quick(value=known):
                                session.database.rate_card(entry.question.id, value)
                                if value:
                                    view.quick_entries.pop(view.quick_index)
                                if not view.quick_entries:
                                    view.page = "modes"
                                else:
                                    view.quick_index = min(view.quick_index + (not value), len(view.quick_entries) - 1)

                            bind(button, rate_quick)

            elif view.page == "cram" and subject and report:
                if view.cram is None:
                    view.cram = CrammingService(session.database, subject.questions, report.answers)
                    if view.cram.questions:
                        view.cram.resume_or_start()
                if not view.cram.questions:
                    heading("Học cấp tốc")
                    badge("Chế độ này cần câu hỏi có đáp án hợp lệ")
                elif view.cram_cursor is not None:
                    old, selected, correct = view.cram_history[view.cram_cursor]
                    heading("Học cấp tốc", f"Xem lại {view.cram_cursor + 1}/{len(view.cram_history)} · Chỉ xem")
                    with gr.Row(elem_classes="src-question-row"):
                        with gr.Column(scale=3, min_width=300):
                            question_panel(old)
                        with gr.Column(scale=1, min_width=230, elem_classes="src-panel"):
                            heading("Bạn chọn", selected)
                            badge(f"Đáp án: {old.correct_answer} · {'Đúng' if correct else 'Sai'}")
                    with gr.Row():
                        previous = gr.Button("Câu trước", interactive=view.cram_cursor > 0, elem_classes="src-icon-ArrowLeft")
                        following = gr.Button("Câu sau", elem_classes="src-icon-ArrowRight")
                    bind(previous, lambda: setattr(view, "cram_cursor", view.cram_cursor - 1))
                    bind(following, lambda: setattr(view, "cram_cursor", None if view.cram_cursor == len(view.cram_history) - 1 else view.cram_cursor + 1))
                else:
                    cycle = view.cram.state()
                    pending = view.cram_pending
                    shown = pending[0] if pending else cycle
                    question = pending[1] if pending else cycle.question
                    heading("Học cấp tốc", f"Vòng {shown.current_round}/{shown.total_rounds} · Còn {cycle.remaining} · Đã thuộc {cycle.mastered}")
                    if question is None:
                        badge(f"Hoàn thành · Đã thuộc {cycle.mastered} · Sai {cycle.wrong} lần")
                        restart = gr.Button("Bắt đầu vòng mới", variant="primary", elem_classes="src-icon-RotateCcw")
                        bind(restart, lambda: (view.cram.start_new(), view.cram_history.clear(), setattr(view, "selection", "")))
                    else:
                        with gr.Row(elem_classes="src-question-row"):
                            with gr.Column(scale=3, min_width=300):
                                question_panel(question)
                            with gr.Column(scale=1, min_width=230, elem_classes="src-panel"):
                                heading("Chọn các đáp án" if question.is_multiple else "Chọn đáp án")
                                def select(option):
                                    view.selection = normalize_answer(view.selection.replace(option, "") if option in view.selection else view.selection + option) if question.is_multiple else ("" if view.selection == option else option)

                                answer_buttons(question, view.selection, pending is not None, bind, select)
                                if pending:
                                    badge("Đúng" if pending[3] else "Sai")
                                    badge(f"Đáp án: {question.correct_answer}")
                                    following = gr.Button("Câu tiếp", variant="primary", elem_classes="src-icon-ArrowRight")
                                    bind(following, lambda: (setattr(view, "cram_pending", None), setattr(view, "selection", "")))
                                else:
                                    check = gr.Button("Kiểm tra", variant="primary", elem_classes="src-icon-Check")

                                    def check_answer():
                                        if not view.selection:
                                            raise ValueError("Hãy chọn đáp án.")
                                        correct = view.cram.is_answer_correct(question, view.selection)
                                        view.cram.rate_current(correct)
                                        view.cram_history.append((question, view.selection, correct))
                                        view.cram_pending = (cycle, question, view.selection, correct)

                                    bind(check, check_answer)
                                restart = gr.Button("Bắt đầu vòng mới", elem_classes="src-icon-RotateCcw")
                                bind(restart, lambda: (view.cram.start_new(), view.cram_history.clear(), setattr(view, "cram_pending", None), setattr(view, "selection", "")))
                        if view.cram_history:
                            history = gr.Button("Xem câu đã làm", elem_classes="src-icon-ArrowLeft")
                            bind(history, lambda: setattr(view, "cram_cursor", len(view.cram_history) - 1))
            elif view.page == "exam" and subject and report:
                if view.exam is None:
                    heading("Tạo bộ đề thi", subject.name)
                    service = ExamService(session.database, subject.questions, report.answers)
                    available = service.eligible_questions(tuple(CATEGORY_LABELS))
                    if not available:
                        badge("Chế độ này cần câu hỏi có đáp án hợp lệ")
                    else:
                        categories = gr.Dropdown(label="Loại câu hỏi", choices=[(CATEGORY_LABELS[key], key) for key in CATEGORY_LABELS], value=sorted({q.category for q in available}), multiselect=True, interactive=True)
                        count = gr.Number(label="Số câu", value=min(10, len(available)), minimum=1, maximum=len(available), precision=0, interactive=True)
                        duration = gr.Number(label="Thời gian (phút)", value=30, minimum=1, maximum=180, precision=0, interactive=True)
                        heading("Chấm điểm")
                        with gr.Row():
                            for value, label in ((FeedbackMode.DEFERRED, "Chấm sau khi nộp"), (FeedbackMode.IMMEDIATE, "Chấm từng câu")):
                                button = gr.Button(label, variant="primary" if view.feedback == value else "secondary")
                                bind(button, lambda chosen=value: setattr(view, "feedback", chosen))
                        start = gr.Button("Bắt đầu thi", variant="primary", elem_classes="src-icon-ArrowRight")

                        def start_exam(selected_categories, number, minutes):
                            config = ExamConfig(subject.name, tuple(selected_categories or ()), int(number), int(minutes), view.feedback)
                            view.exam = service.create_session(config)
                            view.exam_deadline = time.monotonic() + int(minutes) * 60
                            view.confirm_submit = False

                        bind(start, start_exam, [categories, count, duration])
                else:
                    exam = view.exam
                    if time.monotonic() >= view.exam_deadline:
                        submit_exam(view, "time")
                    else:
                        item = exam.current
                        heading("Mock Exam", f"{subject.name} · Câu {exam.current_index + 1}/{len(exam.items)}")
                        deadline_epoch = int(time.time() + max(0, view.exam_deadline - time.monotonic()))
                        gr.HTML(f'<span class="src-pill src-clock" data-end="{deadline_epoch}">⏱ --:--</span>')
                        gr.HTML(f'<div class="src-progress"><span style="width:{100 * (exam.current_index + 1) / len(exam.items):.1f}%"></span></div>')
                        with gr.Row(elem_classes="src-question-row"):
                            with gr.Column(scale=3, min_width=300):
                                question_panel(item.question)
                            with gr.Column(scale=1, min_width=230, elem_classes="src-panel"):
                                heading("Chọn các đáp án" if item.question.is_multiple else "Chọn đáp án")

                                def select_exam(option):
                                    selected = item.selected_answer
                                    value = normalize_answer(selected.replace(option, "") if option in selected else selected + option) if item.question.is_multiple else ("" if selected == option else option)
                                    exam.set_answer(value)

                                answer_buttons(item.question, item.selected_answer, item.confirmed, bind, select_exam)
                                if item.confirmed:
                                    badge(f"Đáp án: {item.question.correct_answer} · {'Đúng' if item.is_correct else 'Sai'}")
                                if exam.config.feedback_mode == FeedbackMode.IMMEDIATE and not item.confirmed:
                                    check = gr.Button("Chấm câu", variant="primary", elem_classes="src-icon-Check")
                                    bind(check, exam.confirm_current)
                                badge(f"Đã trả lời {sum(bool(q.selected_answer) for q in exam.items)}/{len(exam.items)}")
                        can_navigate = exam.config.feedback_mode == FeedbackMode.DEFERRED or item.confirmed
                        with gr.Row():
                            previous = gr.Button("Trước", interactive=exam.current_index > 0 and can_navigate, elem_classes="src-icon-ArrowLeft")
                            following = gr.Button("Tiếp", interactive=exam.current_index < len(exam.items) - 1 and can_navigate, elem_classes="src-icon-ArrowRight")
                            submit = gr.Button("Nộp bài", variant="primary", elem_classes="src-icon-Check")
                        bind(previous, lambda: setattr(exam, "current_index", exam.current_index - 1))
                        bind(following, lambda: setattr(exam, "current_index", exam.current_index + 1))
                        bind(submit, lambda: setattr(view, "confirm_submit", True))
                        if view.confirm_submit:
                            badge(f"Còn {sum(not q.selected_answer for q in exam.items)} câu chưa trả lời. Nộp bài ngay?")
                            with gr.Row():
                                yes = gr.Button("Xác nhận nộp bài", variant="primary")
                                no = gr.Button("Tiếp tục làm bài")
                            bind(yes, lambda: submit_exam(view, "user"))
                            bind(no, lambda: setattr(view, "confirm_submit", False))
                        choices = [(f"Câu {i+1} · {'đã trả lời' if q.selected_answer else 'chưa trả lời'}", i) for i, q in enumerate(exam.items)]
                        jump_to = gr.Dropdown(label="Chuyển nhanh đến câu", choices=choices, value=exam.current_index, interactive=True)
                        jump = gr.Button("Đi đến câu", interactive=can_navigate, elem_classes="src-icon-ArrowRight")
                        bind(jump, lambda index: setattr(exam, "current_index", int(index)), [jump_to])

            elif view.page == "result" and view.exam_result:
                result = view.exam_result
                heading("Kết quả bài thi", result.config.subject)
                badge(f"{result.score}/10 · {result.status} · Đúng {result.correct}/{result.total} · Bỏ trống {result.unanswered}")
                for number, item in enumerate(result.items, 1):
                    with gr.Accordion(f"Câu {number}: chọn {item.selected_answer or '—'} · đúng {item.question.correct_answer} · {item.awarded_score:.2f} điểm", open=False):
                        question_panel(item.question)
                with gr.Row():
                    retest = gr.Button("Làm lại cấu hình cũ", variant="primary", elem_classes="src-icon-RotateCcw")
                    configure = gr.Button("Tự chọn cấu hình mới")
                    home_button = gr.Button("Về thư viện", elem_classes="src-icon-ArrowLeft")

                def restart_exam():
                    selected_subject = session.subjects[result.config.subject]
                    answers = session.answer_reports[result.config.subject].answers
                    view.exam = ExamService(session.database, selected_subject.questions, answers).create_session(result.config)
                    view.exam_deadline = time.monotonic() + result.config.duration_minutes * 60
                    view.exam_result = None
                    view.page = "exam"

                bind(retest, restart_exam)
                bind(configure, lambda: (setattr(view, "exam_result", None), navigate("exam")))
                bind(home_button, lambda: navigate("home"))

            elif view.page == "history":
                heading("Lịch sử bài thi")
                subjects = [view.subject_name] if view.subject_name else sorted(session.subjects)
                rows = [row for name in subjects for row in session.database.exam_history(name)]
                if rows:
                    for row in rows[:20]:
                        badge(f"Bài #{row['id']} · {row['score']}/10 · {row['correct']}/{row['total']} câu đúng")
                else:
                    badge("Chưa có bài thi trong phiên Colab này")

            elif view.page == "settings":
                heading("Cài đặt", "Phiên Colab hiện tại")
                gr.HTML('<div class="src-panel">DATA và tiến độ SQLite nằm trong runtime Colab tạm. Chạy lại notebook tạo phiên mới. Ảnh câu hỏi được che vùng đáp án như app Desktop.</div>')

            else:
                view.page = "home"
                badge("Không tìm thấy màn hình. Hãy quay lại thư viện.")

        def on_tick(version: int, request: gr.Request):
            view = view_for(request.session_hash)
            if view.exam is not None and time.monotonic() >= view.exam_deadline:
                submit_exam(view, "time")
                return version + 1
            return gr.skip()

        tick.tick(on_tick, inputs=revision, outputs=revision)
    return demo


def answer_buttons(question: Question, selected: str, disabled: bool, bind, select) -> None:
    for start in range(0, len(question.options), 2):
        with gr.Row(elem_classes="src-answer-row"):
            for option in question.options[start:start + 2]:
                button = gr.Button(option, variant="primary" if option in selected else "secondary",
                                   interactive=not disabled, elem_classes="src-answer-button", min_width=72)
                bind(button, lambda value=option: select(value))
    if not disabled:
        gr.HTML('<p class="src-muted">Chạm lần nữa để bỏ chọn</p>')


def submit_exam(view: ViewState, reason: str) -> None:
    if view.exam is not None and not view.exam.submitted:
        view.exam_result = view.exam.submit(reason)
        view.exam = None
        view.confirm_submit = False
        view.page = "result"


def launch_app(*, share: bool, prevent_thread_lock: bool = False):
    base = Path(__file__).parent
    css = (base / "gradio.css").read_text(encoding="utf-8")
    icons = (base / "icons" / "icon_runtime.js").read_text(encoding="utf-8")
    demo = create_app()
    _, local_url, share_url = demo.launch(
        server_name="127.0.0.1", share=share, inline=False,
        prevent_thread_lock=prevent_thread_lock, css=css,
        head=f"<script>{icons}</script>", footer_links=[], run_history=False,
    )
    return demo, local_url, share_url


if __name__ == "__main__":
    launch_app(share=os.environ.get("SRC_LEARNING_SHARE") == "1")
