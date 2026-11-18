from __future__ import annotations

import pytest

from app.repositories.database import Database
from app.services.data_scanner import DataScannerService
from app.services.study import FlashcardService
from tools.flashcard_release_qa import check_flash_profile, make_flash_profile, windows_flashcard_qa


def test_profile_gate_accepts_only_intentional_ratings_and_resumes_the_same_session(tmp_path):
    state = make_flash_profile(tmp_path)
    ail = next(subject for subject in DataScannerService(state["path"] / "DATA").scan() if subject.name == "AIL303m")
    ratings = [True, False, True]
    database = Database(state["database"])
    try:
        service = FlashcardService(database, ail.questions)
        assert service.resume_or_start().session_id == state["session_id"]
        for known in ratings:
            service.rate_current(known)
    finally:
        database.close()
    check_flash_profile(state, ratings)
    database = Database(state["database"])
    try:
        resumed = FlashcardService(database, ail.questions)
        assert resumed.resume_or_start().position == 4
        assert resumed.session_id == state["session_id"]
        assert resumed.order == state["order"]
    finally:
        database.close()
    check_flash_profile(state, ratings)


@pytest.mark.parametrize("fault", ["session", "unrelated_progress", "question_data"])
def test_profile_gate_rejects_progress_reset_or_unrelated_mutation(tmp_path, fault):
    state = make_flash_profile(tmp_path)
    if fault == "question_data":
        with next((state["path"] / "DATA").rglob("*.png")).open("ab") as stream:
            stream.write(b"unintended change")
    else:
        database = Database(state["database"])
        try:
            if fault == "session":
                database.delete_active_flash_session("AIL303m")
            else:
                subject = next(s for s in DataScannerService(state["path"] / "DATA").scan() if s.name == "CPV301")
                database.rate_card(subject.questions[0].id, True)
        finally:
            database.close()
    with pytest.raises(AssertionError):
        check_flash_profile(state, [])


def test_native_gate_refuses_to_control_a_non_runner_desktop(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(ValueError, match="isolated GitHub Windows runner"):
        windows_flashcard_qa(tmp_path, tmp_path / "not-launched.exe")
