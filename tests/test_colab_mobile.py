"""Verify fresh Colab state and the three shared learning backends."""
from __future__ import annotations
import csv
import io
from pathlib import Path
from PIL import Image
import pytest
from app.domain.models import ExamConfig, FeedbackMode
from app.services.data_package_installer import DataInstallResult
from app.services.exam import ExamService
from app.services.study import CrammingService, FlashcardService
from colab_mobile.image import question_image
from colab_mobile.session import MobileLearningSession

class FakeInstaller:
    def install(self, code, data_dir, *, progress=None):
        assert code == "approved-example-id"
        subject_dir = Path(data_dir) / "DEMO101"
        category_dir = subject_dir / "Selections_1_choose"
        category_dir.mkdir(parents=True)
        for index in range(2):
            Image.new("RGB", (100, 100), "white").save(category_dir / f"Question_{index + 1}.png")
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

def test_three_modes_use_same_backend_and_mask(tmp_path: Path) -> None:
    session = MobileLearningSession(tmp_path / "modes", installer=FakeInstaller())
    session.install_subject("approved-example-id")
    subject = session.subjects["DEMO101"]
    answers = session.answer_reports["DEMO101"].answers
    with Image.open(io.BytesIO(question_image(subject.questions[0].absolute_path))) as cropped:
        assert cropped.size == (100, 90)
    flash = FlashcardService(session.database, subject.questions, answers)
    assert flash.resume_or_start().total == 2
    flash.rate_current(True)
    assert flash.stats()["known"] == 1
    cram = CrammingService(session.database, subject.questions, answers)
    assert cram.resume_or_start().question is not None
    assert cram.is_answer_correct(cram.state().question, cram.state().question.correct_answer)
    cram.rate_current(True)
    assert cram.state().mastered == 1
    exam = ExamService(session.database, subject.questions, answers).create_session(
        ExamConfig("DEMO101", ("Selections_1_choose",), 2, 30, FeedbackMode.DEFERRED)
    )
    exam.set_answer(exam.current.question.correct_answer)
    result = exam.submit("user")
    assert result.total == 2 and result.correct == 1
    assert len(session.database.exam_history("DEMO101")) == 1
    session.close()


def test_streamlit_import_progress_stays_on_ui_thread(tmp_path: Path) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    session = MobileLearningSession(tmp_path / "streamlit", installer=FakeInstaller())
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "colab_mobile" / "streamlit_app.py")).run(timeout=20)
    app.session_state["learning_session"] = session
    app.session_state["page"] = "add"
    app.run(timeout=20)
    app.text_input[0].set_value("approved-example-id").run(timeout=20)
    next(button for button in app.button if button.label == "Tải môn học").click().run(timeout=20)
    assert not app.exception
    assert app.session_state["page"] == "modes"
    assert app.session_state["subject_name"] == "DEMO101"
    session.close()
