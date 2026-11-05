"""Exercise the notebook adapter without contacting Google Drive or Colab."""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path

import pytest
from PIL import Image

from app.services.data_package_installer import DataInstallResult
from colab_mobile.session import MobileLearningSession


class FakeInstaller:
    def install(self, code, data_dir, *, progress=None):
        assert code == "approved-example-id"
        subject_dir = Path(data_dir) / "DEMO101"
        category_dir = subject_dir / "Selections_1_choose"
        category_dir.mkdir(parents=True)
        for index in range(2):
            Image.new("RGB", (100, 100), "white").save(
                category_dir / f"Question_{index + 1}.png"
            )
        with (subject_dir / "answers.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["image_name", "correct_answer"])
            writer.writerow(["Selections_1_choose/Question_1.png", "A"])
            writer.writerow(["Selections_1_choose/Question_2.png", "B"])
        if progress:
            progress("complete", 100, "Đã cài")
        return DataInstallResult("DEMO101", subject_dir, 2, "0" * 64)


def test_mobile_session_installs_and_starts_with_fresh_sqlite(tmp_path: Path) -> None:
    first = MobileLearningSession(tmp_path / "first", installer=FakeInstaller())
    result = first.install_subject("approved-example-id")
    assert result.question_count == 2
    assert first.subjects["DEMO101"].question_count == 2
    assert first.answer_reports["DEMO101"].valid_count == 2
    first.database.rate_card(first.subjects["DEMO101"].questions[0].id, True)
    assert first.database.card_stats("DEMO101")["known"] == 1

    second = MobileLearningSession(tmp_path / "second", installer=FakeInstaller())
    second.install_subject("approved-example-id")
    assert second.database.card_stats("DEMO101")["known"] == 0
    assert first.database.path != second.database.path
    first.close()
    second.close()


def test_notebook_ui_covers_three_modes_and_crops_image(tmp_path: Path) -> None:
    widgets = pytest.importorskip("ipywidgets")
    from colab_mobile.ui import NotebookLearningUI, question_image

    session = MobileLearningSession(tmp_path / "ui", installer=FakeInstaller())
    ui = NotebookLearningUI(session)
    ui.code.value = "approved-example-id"
    ui.install.click()
    assert ui.subject.value == "DEMO101"
    assert ui.flash is not None

    question = session.subjects["DEMO101"].questions[0]
    with Image.open(io.BytesIO(question_image(question.absolute_path))) as cropped:
        assert cropped.size == (100, 90)

    session.database.record_question_attempt(question.id, correct=False)
    ui._render()
    next(child for row in ui.body.children for child in getattr(row, "children", ())
         if isinstance(child, widgets.Button) and child.description == "Ôn câu sai nhiều").click()
    assert ui.quick_reviews is not None and not ui.quick_ratable
    next(child for row in ui.body.children for child in getattr(row, "children", ())
         if isinstance(child, widgets.Button) and child.description == "Đóng ôn tập").click()
    next(child for row in ui.body.children for child in getattr(row, "children", ())
         if isinstance(child, widgets.Button) and child.description == "Ôn câu mới/chưa thuộc").click()
    assert ui.quick_reviews is not None and ui.quick_ratable
    next(child for row in ui.body.children for child in getattr(row, "children", ())
         if isinstance(child, widgets.Button) and child.description == "Đã thuộc").click()
    assert session.database.card_stats("DEMO101")["known"] == 1
    ui._close_quick()

    ui.mode.value = "cram"
    assert ui.cram is not None
    control = next(child for child in ui.body.children if isinstance(child, widgets.RadioButtons))
    control.value = ui.cram.state().question.correct_answer
    next(child for row in ui.body.children for child in getattr(row, "children", ())
         if isinstance(child, widgets.Button) and child.description == "Kiểm tra").click()
    next(child for row in ui.body.children for child in getattr(row, "children", ())
         if isinstance(child, widgets.Button) and child.description == "Câu tiếp").click()
    assert ui.cram.state().mastered == 1

    ui.mode.value = "exam"
    next(child for row in ui.body.children for child in getattr(row, "children", ())
         if isinstance(child, widgets.Button) and child.description == "Bắt đầu thi").click()
    assert ui.exam is not None and len(ui.exam.items) == 2
    control = next(child for child in ui.body.children if isinstance(child, widgets.RadioButtons))
    control.value = ui.exam.current.question.correct_answer
    next(child for row in ui.body.children for child in getattr(row, "children", ())
         if isinstance(child, widgets.Button) and child.description == "Nộp bài").click()
    assert ui.exam_result is not None
    assert ui.exam_result.total == 2
    assert ui.exam_result.correct == 1
    assert len(session.database.exam_history("DEMO101")) == 1
    ui.close()


def test_exam_immediate_feedback_and_deadline(tmp_path: Path) -> None:
    widgets = pytest.importorskip("ipywidgets")
    from app.domain.models import FeedbackMode
    from colab_mobile.ui import NotebookLearningUI

    session = MobileLearningSession(tmp_path / "timed", installer=FakeInstaller())
    session.install_subject("approved-example-id")
    ui = NotebookLearningUI(session)
    ui.subject.options = ["DEMO101"]
    ui.subject.value = "DEMO101"
    ui.mode.value = "exam"
    feedback = next(child for child in ui.body.children if isinstance(child, widgets.Dropdown))
    feedback.value = FeedbackMode.IMMEDIATE
    next(child for row in ui.body.children for child in getattr(row, "children", ())
         if isinstance(child, widgets.Button) and child.description == "Bắt đầu thi").click()
    assert ui.subject.disabled
    control = next(child for child in ui.body.children if isinstance(child, widgets.RadioButtons))
    control.value = ui.exam.current.question.correct_answer
    next(child for row in ui.body.children for child in getattr(row, "children", ())
         if isinstance(child, widgets.Button) and child.description == "Chấm câu").click()
    assert ui.exam.current.confirmed
    ui.exam_deadline = time.monotonic() - 1
    ui._render()
    assert ui.exam_result is not None
    assert not ui.subject.disabled
    assert session.database.exam_history("DEMO101")[0]["submit_reason"] == "time"
    ui.close()
