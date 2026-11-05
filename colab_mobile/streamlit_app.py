"""Desktop-inspired SRC LEARNING interface inside a Colab output frame."""

from __future__ import annotations

import html
import os
import time
from pathlib import Path

import streamlit as st

from app.config import CATEGORY_LABELS
from app.domain.models import ExamConfig, FeedbackMode, Question, normalize_answer
from app.services.adaptive import AdaptiveReviewService
from app.services.exam import ExamService
from app.services.study import CrammingService, FlashcardService
from colab_mobile.image import question_image
from colab_mobile.session import MobileLearningSession


st.set_page_config(page_title="SRC Learning", page_icon="📘", layout="wide", initial_sidebar_state="collapsed")
st.html(Path(__file__).with_name("style.css").read_text(encoding="utf-8"))


def init() -> None:
    state = st.session_state
    if "learning_session" not in state:
        runtime_root = os.environ.get("SRC_LEARNING_SESSION_ROOT")
        state.learning_session = MobileLearningSession(Path(runtime_root) if runtime_root else None)
        if runtime_root:
            state.learning_session.refresh_subjects()
        state.page = "home"
        state.subject_name = ""
        state.flash = None
        state.cram = None
        state.exam = None
        state.exam_result = None
        state.exam_deadline = 0.0
        state.revealed = False
        state.cram_checked = None
        state.quick_entries = None
        state.quick_index = 0
        state.quick_ratable = False
        state.flash_history = []
        state.flash_cursor = None
        state.confirm_submit = False
        state.notice = ""


def go(page: str) -> None:
    st.session_state.page = page
    st.rerun()


def reset_mode() -> None:
    state = st.session_state
    state.flash = None
    state.cram = None
    state.exam = None
    state.exam_result = None
    state.revealed = False
    state.cram_checked = None
    state.quick_entries = None
    state.flash_history = []
    state.flash_cursor = None
    state.confirm_submit = False


def current():
    session = st.session_state.learning_session
    name = st.session_state.subject_name
    return session.subjects.get(name), session.answer_reports.get(name)


def header() -> None:
    with st.container(key="src_toolbar"):
        cols = st.columns([6, 1, 1, 1, 1], vertical_alignment="center")
        with cols[0]:
            st.markdown('<div class="src-logo"><span class="src-logo-mark">✦</span> SRC Learning</div>', unsafe_allow_html=True)
        with cols[1]:
            if st.button("＋", help="Thêm môn", width="stretch"):
                go("add")
        with cols[2]:
            if st.button("◷", help="Lịch sử bài thi", width="stretch"):
                go("history")
        with cols[3]:
            if st.button("⟳", help="Quét lại thư viện", width="stretch"):
                st.session_state.learning_session.refresh_subjects()
                st.rerun()
        with cols[4]:
            if st.button("⚙", help="Cài đặt", width="stretch"):
                go("settings")
    st.markdown('<div class="src-divider"></div>', unsafe_allow_html=True)


def back(target="modes") -> None:
    if st.button("← Quay lại"):
        go(target)


def subject_header(title: str, subtitle: str = "") -> None:
    back()
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def image_view(question: Question) -> None:
    try:
        st.image(question_image(question.absolute_path), width="stretch")
    except (OSError, ValueError) as exc:
        st.error(f"Không đọc được ảnh câu hỏi: {exc}")


def answer_input(question: Question, key: str, selected: str = "") -> str:
    options = list(question.options)
    if question.is_multiple:
        choices = st.multiselect("Chọn đáp án", options, default=list(selected), key=key)
        return normalize_answer("".join(choices))
    choices = ["— Chưa chọn —", *options]
    index = choices.index(selected) if selected in choices else 0
    value = st.radio("Chọn đáp án", choices, index=index, horizontal=True, key=key)
    return "" if value == choices[0] else value


def home() -> None:
    st.title("Thư viện")
    st.markdown('<p class="src-lead">Chọn môn học để bắt đầu ôn tập</p>', unsafe_allow_html=True)
    session = st.session_state.learning_session
    if not session.subjects:
        with st.container(border=True):
            st.info("Thư viện đang trống. Nhập Drive ID của môn đã được phê duyệt để tải dữ liệu.")
            if st.button("＋ Thêm môn học", type="primary"):
                go("add")
        return
    for name, subject in sorted(session.subjects.items()):
        with st.container(border=True):
            left, middle, right = st.columns([1, 5, 2], vertical_alignment="center")
            with left:
                st.markdown(f'<div class="src-subject-monogram">{html.escape(name[:3].upper())}</div>', unsafe_allow_html=True)
            with middle:
                st.subheader(name)
                st.caption(f"{subject.question_count} câu hỏi · {len(subject.category_counts)} loại câu")
            with right:
                if st.button("Mở môn học →", key=f"open-{name}", type="primary", width="stretch"):
                    st.session_state.subject_name = name
                    reset_mode()
                    go("modes")


def add_subject() -> None:
    back("home")
    st.title("Thêm môn học")
    st.caption("Nhập Google Drive File ID hoặc link chia sẻ của gói đã có trong danh mục SRC Learning.")
    with st.container(border=True):
        code = st.text_input("Drive ID hoặc link chia sẻ", placeholder="Dán ID môn học")
        if st.button("Tải môn học", type="primary", disabled=not code.strip()):
            progress = st.progress(0, text="Đang chuẩn bị...")
            try:
                result = st.session_state.learning_session.install_subject(
                    code.strip(),
                    progress=lambda _stage, percent, message: progress.progress(
                        min(100, max(0, percent)), text=message
                    ),
                )
            except Exception as exc:
                st.error(f"Không tải được môn: {exc}")
            else:
                st.session_state.subject_name = result.subject
                reset_mode()
                st.session_state.notice = f"Đã tải {result.subject}: {result.question_count} câu hỏi."
                go("modes")


def modes() -> None:
    subject, report = current()
    if subject is None or report is None:
        go("home")
    back("home")
    st.title(subject.name)
    st.caption(f"{subject.question_count} câu hỏi · {report.valid_count} câu có đáp án")
    if st.session_state.notice:
        st.success(st.session_state.notice)
        st.session_state.notice = ""
    cards = [
        ("flash", "▣", "Học bình thường", "Lật thẻ, tự đánh giá đã thuộc hoặc chưa thuộc."),
        ("cram", "⚡", "Học cấp tốc", "Trả lời theo vòng, ôn lại câu sai."),
        ("exam", "◷", "Tạo bộ đề thi", "Chọn số câu, thời gian và cách chấm."),
    ]
    for column, (page, icon, title, description) in zip(st.columns(3), cards, strict=True):
        with column, st.container(border=True):
            st.markdown(f'<div class="src-card-icon">{icon}</div><div class="src-card-title">{title}</div><p class="src-card-desc">{description}</p>', unsafe_allow_html=True)
            if st.button("Bắt đầu →", key=f"mode-{page}", type="primary", width="stretch"):
                go(page)
    st.subheader("Tiến độ học tập")
    stats = st.session_state.learning_session.database.card_stats(subject.name)
    a, b, c = st.columns(3)
    a.metric("Đã thuộc", stats["known"])
    b.metric("Chưa thuộc", stats["learning"])
    c.metric("Tổng câu", subject.question_count)
    st.subheader("Ôn tập nhanh")
    adaptive = AdaptiveReviewService(st.session_state.learning_session.database, subject.questions, report.answers)
    learning = [entry for group in adaptive.learning_by_category().values() for entry in group]
    weak = [entry for group in adaptive.top_errors_by_category().values() for entry in group]
    a, b = st.columns(2)
    with a:
        if st.button(f"Ôn câu mới/chưa thuộc ({len(learning)})", disabled=not learning, width="stretch"):
            st.session_state.quick_entries = learning
            st.session_state.quick_index = 0
            st.session_state.quick_ratable = True
            go("quick")
    with b:
        if st.button(f"Ôn câu sai nhiều ({len(weak)})", disabled=not weak, width="stretch"):
            st.session_state.quick_entries = weak
            st.session_state.quick_index = 0
            st.session_state.quick_ratable = False
            go("quick")


def flash() -> None:
    subject, report = current()
    if subject is None:
        go("home")
    state = st.session_state
    if state.flash is None:
        state.flash = FlashcardService(state.learning_session.database, subject.questions, report.answers)
        state.flash.resume_or_start()
    card = state.flash.state()
    stats = state.flash.stats()
    subject_header("Flash Cards", f"{subject.name} · Đã thuộc {stats['known']} · Chưa thuộc {stats['learning']}")
    if state.flash_cursor is not None:
        old_question, was_known = state.flash_history[state.flash_cursor]
        st.caption(f"Xem lại {state.flash_cursor + 1}/{len(state.flash_history)} · {'Đã thuộc' if was_known else 'Chưa thuộc'} · Chỉ xem")
        picture, side = st.columns([3, 1])
        with picture:
            image_view(old_question)
        with side, st.container(border=True):
            st.markdown(f'<div class="src-answer">Đáp án: {html.escape(old_question.correct_answer or "Chưa có")}</div>', unsafe_allow_html=True)
        previous, following = st.columns(2)
        with previous:
            if st.button("← Câu trước", disabled=state.flash_cursor == 0, width="stretch"):
                state.flash_cursor -= 1
                st.rerun()
        with following:
            if st.button("Câu sau →", width="stretch"):
                state.flash_cursor = None if state.flash_cursor == len(state.flash_history) - 1 else state.flash_cursor + 1
                st.rerun()
        return
    if card.completed or card.question is None:
        st.success("Đã hết thẻ trong phiên này.")
    else:
        st.progress((card.position + 1) / card.total, text=f"Thẻ {card.position + 1}/{card.total}")
        picture, side = st.columns([3, 1], gap="medium")
        with picture:
            image_view(card.question)
        with side, st.container(border=True):
            st.markdown('<div class="src-pill"><span class="src-pill-dot"></span>FLASH CARDS</div>', unsafe_allow_html=True)
            st.subheader(f"Câu {card.position + 1}")
            st.caption(CATEGORY_LABELS.get(card.question.category, card.question.category))
            st.markdown('<div class="src-divider"></div>', unsafe_allow_html=True)
            if state.revealed:
                st.markdown(f'<div class="src-answer">Đáp án: {html.escape(card.question.correct_answer or "Chưa có")}</div>', unsafe_allow_html=True)
            else:
                st.caption("Xem câu hỏi rồi hiện đáp án để tự đánh giá.")
        with st.container(key="src_flash_actions"):
            actions = st.columns([1, 1, 1.2, 1, 1])
            with actions[0]:
                if st.button("Học lại", width="stretch"):
                    state.flash.restart()
                    state.revealed = False
                    state.flash_history = []
                    st.rerun()
            with actions[1]:
                if st.button("Chỉ học Chưa thuộc", width="stretch"):
                    try:
                        state.flash.start_new(True)
                        state.revealed = False
                        state.flash_history = []
                        st.rerun()
                    except ValueError as exc:
                        st.warning(str(exc))
            with actions[2]:
                if st.button("Hiện đáp án", type="primary", width="stretch"):
                    state.revealed = True
                    st.rerun()
            for column, label, known in ((actions[3], "Chưa thuộc", False), (actions[4], "Đã thuộc", True)):
                with column:
                    if st.button(label, disabled=not state.revealed, width="stretch"):
                        state.flash_history.append((card.question, known))
                        state.flash.rate_current(known)
                        state.revealed = False
                        st.rerun()
        navigation = st.columns(2)
        with navigation[0]:
            if st.button("← Câu trước", disabled=not state.flash_history, width="stretch"):
                state.flash_cursor = len(state.flash_history) - 1
                st.rerun()
        with navigation[1]:
            if st.button("Bỏ qua / Câu sau →", width="stretch"):
                state.flash_history.append((card.question, False))
                state.flash.rate_current(False)
                state.revealed = False
                st.rerun()
        return
    if st.button("Học lại tất cả", type="primary"):
        state.flash.restart()
        state.revealed = False
        state.flash_history = []
        st.rerun()
    if state.flash_history and st.button("← Xem câu vừa học"):
        state.flash_cursor = len(state.flash_history) - 1
        st.rerun()


def quick() -> None:
    entries = st.session_state.quick_entries
    if not entries:
        go("modes")
    state = st.session_state
    entry = entries[state.quick_index]
    subject_header("Ôn tập nhanh", f"Câu {state.quick_index + 1}/{len(entries)}")
    picture, side = st.columns([3, 1])
    with picture:
        image_view(entry.question)
    with side, st.container(border=True):
        st.markdown(f'<div class="src-answer">Đáp án: {html.escape(entry.correct_answer or "Chưa có")}</div>', unsafe_allow_html=True)
        st.caption(CATEGORY_LABELS.get(entry.question.category, entry.question.category))
    controls = st.columns(4)
    with controls[0]:
        if st.button("← Trước", disabled=state.quick_index == 0):
            state.quick_index -= 1
            st.rerun()
    with controls[1]:
        if st.button("Tiếp →", disabled=state.quick_index >= len(entries) - 1):
            state.quick_index += 1
            st.rerun()
    if state.quick_ratable:
        for column, label, known in ((controls[2], "Chưa thuộc", False), (controls[3], "Đã thuộc", True)):
            with column:
                if st.button(label):
                    state.learning_session.database.rate_card(entry.question.id, known)
                    if known:
                        entries.pop(state.quick_index)
                    if not entries:
                        state.quick_entries = None
                        go("modes")
                    state.quick_index = min(state.quick_index + (not known), len(entries) - 1)
                    st.rerun()


def cram() -> None:
    subject, report = current()
    if subject is None:
        go("home")
    state = st.session_state
    if state.cram is None:
        state.cram = CrammingService(state.learning_session.database, subject.questions, report.answers)
        if not state.cram.questions:
            subject_header("Học cấp tốc")
            st.warning("Chế độ này cần câu hỏi có đáp án hợp lệ.")
            return
        state.cram.resume_or_start()
    cycle = state.cram.state()
    subject_header("Học cấp tốc", f"Vòng {cycle.current_round}/{cycle.total_rounds} · Còn {cycle.remaining} · Đã thuộc {cycle.mastered}")
    if cycle.completed or cycle.question is None:
        st.success(f"Hoàn thành. Đã thuộc {cycle.mastered}, trả lời sai {cycle.wrong} lần.")
        if st.button("Bắt đầu vòng mới", type="primary"):
            state.cram.start_new()
            state.cram_checked = None
            st.rerun()
        return
    picture, side = st.columns([3, 1])
    with picture:
        image_view(cycle.question)
    with side, st.container(border=True):
        selected = answer_input(cycle.question, f"cram-{cycle.cycle_id}-{cycle.question.id}")
        if state.cram_checked is None:
            if st.button("Kiểm tra", type="primary", width="stretch"):
                if selected:
                    state.cram_checked = state.cram.is_answer_correct(cycle.question, selected)
                    st.rerun()
                else:
                    st.warning("Hãy chọn đáp án.")
        else:
            if state.cram_checked:
                st.success("Đúng")
            else:
                st.error("Sai")
            st.markdown(f'**Đáp án: {html.escape(cycle.question.correct_answer)}**')
            if st.button("Câu tiếp →", type="primary", width="stretch"):
                state.cram.rate_current(state.cram_checked)
                state.cram_checked = None
                st.rerun()
        if st.button("Bắt đầu vòng mới", width="stretch"):
            state.cram.start_new()
            state.cram_checked = None
            st.rerun()


def submit_exam(reason: str) -> None:
    state = st.session_state
    if state.exam and not state.exam.submitted:
        state.exam_result = state.exam.submit(reason)
        state.exam = None
        state.confirm_submit = False
        state.page = "result"


def exam() -> None:
    subject, report = current()
    if subject is None:
        go("home")
    state = st.session_state
    if state.exam is None:
        subject_header("Tạo bộ đề thi", subject.name)
        service = ExamService(state.learning_session.database, subject.questions, report.answers)
        available = service.eligible_questions(tuple(CATEGORY_LABELS))
        if not available:
            st.warning("Chế độ này cần câu hỏi có đáp án hợp lệ.")
            return
        with st.container(border=True):
            categories = st.multiselect("Loại câu hỏi", list(CATEGORY_LABELS), default=list({q.category for q in available}), format_func=lambda x: CATEGORY_LABELS[x])
            pool = service.eligible_questions(categories)
            count = st.number_input("Số câu", min_value=1, max_value=max(1, len(pool)), value=min(10, max(1, len(pool))))
            duration = st.number_input("Thời gian (phút)", min_value=1, max_value=180, value=30)
            feedback = st.radio("Chấm điểm", [FeedbackMode.DEFERRED, FeedbackMode.IMMEDIATE], format_func=lambda x: "Chấm sau khi nộp" if x == FeedbackMode.DEFERRED else "Chấm từng câu", horizontal=True)
            if st.button("Bắt đầu thi", type="primary", disabled=not pool):
                try:
                    state.exam = service.create_session(ExamConfig(subject.name, tuple(categories), int(count), int(duration), feedback))
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    state.exam_deadline = time.monotonic() + int(duration) * 60
                    st.rerun()
        if st.button("Lịch sử bài thi"):
            go("history")
        return
    exam = state.exam
    remaining = state.exam_deadline - time.monotonic()
    if remaining <= 0:
        submit_exam("time")
        st.rerun()
    item = exam.current
    subject_header("Mock Exam", f"{subject.name} · Câu {exam.current_index + 1}/{len(exam.items)}")
    @st.fragment(run_every="1s")
    def timer() -> None:
        seconds = max(0, int(state.exam_deadline - time.monotonic()))
        st.markdown(f'<div class="src-pill">⏱ {seconds // 60:02d}:{seconds % 60:02d}</div>', unsafe_allow_html=True)
        if seconds == 0:
            submit_exam("time")
            st.rerun(scope="app")
    timer()
    st.progress((exam.current_index + 1) / len(exam.items))
    picture, side = st.columns([3, 1])
    with picture:
        image_view(item.question)
    with side, st.container(border=True):
        key = f"exam-{id(exam)}-{exam.current_index}"
        selected = answer_input(item.question, key, item.selected_answer)
        if item.confirmed:
            st.markdown(f'**Đáp án: {html.escape(item.question.correct_answer)}**')
        if exam.config.feedback_mode == FeedbackMode.IMMEDIATE and not item.confirmed:
            if st.button("Chấm câu", type="primary", width="stretch"):
                try:
                    exam.set_answer(selected)
                    correct = exam.confirm_current()
                except ValueError as exc:
                    st.warning(str(exc))
                else:
                    state.notice = "Đúng" if correct else "Sai"
                    st.rerun()
        if state.notice:
            st.info(state.notice)
            state.notice = ""
        answered = sum(bool(question.selected_answer) for question in exam.items)
        st.caption(f"Đã trả lời {answered}/{len(exam.items)}")
    def save() -> None:
        if not item.confirmed:
            exam.set_answer(selected)
    can_navigate = exam.config.feedback_mode == FeedbackMode.DEFERRED or item.confirmed
    controls = st.columns([1, 1, 2])
    with controls[0]:
        if st.button("← Trước", disabled=exam.current_index == 0 or not can_navigate, width="stretch"):
            save()
            exam.current_index -= 1
            st.rerun()
    with controls[1]:
        if st.button("Tiếp →", disabled=exam.current_index == len(exam.items) - 1 or not can_navigate, width="stretch"):
            save()
            exam.current_index += 1
            st.rerun()
    with controls[2]:
        if st.button("Nộp bài", type="primary", width="stretch"):
            save()
            state.confirm_submit = True
            st.rerun()
    if state.confirm_submit:
        unanswered = sum(not question.selected_answer for question in exam.items)
        st.warning(f"Bạn còn {unanswered} câu chưa trả lời. Nộp bài ngay?")
        yes, no = st.columns(2)
        with yes:
            if st.button("Xác nhận nộp bài", type="primary", width="stretch"):
                submit_exam("user")
                st.rerun()
        with no:
            if st.button("Tiếp tục làm bài", width="stretch"):
                state.confirm_submit = False
                st.rerun()
    st.markdown("**Chuyển nhanh đến câu**")
    selected_index = st.selectbox(
        "Câu hỏi",
        range(len(exam.items)),
        index=exam.current_index,
        format_func=lambda index: f"Câu {index + 1} · {'đã trả lời' if exam.items[index].selected_answer else 'chưa trả lời'}",
        label_visibility="collapsed",
    )
    if st.button("Đi đến câu", disabled=selected_index == exam.current_index or not can_navigate, width="stretch"):
        save()
        exam.current_index = selected_index
        st.rerun()


def result() -> None:
    result = st.session_state.exam_result
    if result is None:
        go("exam")
    subject_header("Kết quả bài thi", result.config.subject)
    st.metric("Điểm", f"{result.score}/10", result.status)
    st.caption(f"Đúng {result.correct}/{result.total} · Bỏ trống {result.unanswered}")
    for index, item in enumerate(result.items, 1):
        with st.expander(f"Câu {index}: chọn {item.selected_answer or '—'} · đúng {item.question.correct_answer} · {item.awarded_score:.2f} điểm"):
            image_view(item.question)
    retest, configure, home_button = st.columns(3)
    with retest:
        if st.button("↻ Làm lại cấu hình cũ", type="primary", width="stretch"):
            subject, report = current()
            service = ExamService(st.session_state.learning_session.database, subject.questions, report.answers)
            try:
                st.session_state.exam = service.create_session(result.config)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state.exam_deadline = time.monotonic() + result.config.duration_minutes * 60
                st.session_state.exam_result = None
                go("exam")
    with configure:
        if st.button("Tự chọn cấu hình mới", width="stretch"):
            st.session_state.exam_result = None
            go("exam")
    with home_button:
        if st.button("Về thư viện", width="stretch"):
            go("home")


def history() -> None:
    back("modes" if st.session_state.subject_name else "home")
    st.title("Lịch sử bài thi")
    session = st.session_state.learning_session
    subjects = [st.session_state.subject_name] if st.session_state.subject_name else sorted(session.subjects)
    rows = [row for name in subjects for row in session.database.exam_history(name)]
    if not rows:
        st.info("Chưa có bài thi trong phiên Colab này.")
    else:
        for row in rows[:20]:
            st.markdown(f"Bài #{row['id']} · {row['score']}/10 · {row['correct']}/{row['total']} câu đúng")


def settings() -> None:
    back("home")
    st.title("Cài đặt")
    st.caption("Phiên Colab hiện tại")
    st.info("Dữ liệu môn và tiến độ SQLite nằm trong bộ nhớ tạm của runtime Colab. Khởi động lại runtime sẽ tạo phiên mới.")
    st.caption("Ảnh câu hỏi được che vùng đáp án theo cùng mức mặc định của app Desktop.")


init()
header()
page = st.session_state.page
routes = {"home": home, "add": add_subject, "modes": modes, "flash": flash, "quick": quick, "cram": cram, "exam": exam, "result": result, "history": history, "settings": settings}
routes.get(page, home)()
