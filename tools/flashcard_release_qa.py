"""Isolated Flash Cards mouse/keyboard and persisted-session release gate."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from tools.release_gui_qa import PROGRESS_TABLES, digest, marked_workspace, readonly_database


def progress_rows(path: Path) -> dict:
    with readonly_database(path) as connection:
        connection.row_factory = sqlite3.Row
        return {
            table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in (*PROGRESS_TABLES, "question_bank_versions", "question_revisions")
        }


def data_files(profile: Path) -> dict:
    return {
        str(path.relative_to(profile)): digest(path)
        for path in (profile / "DATA").rglob("*") if path.is_file()
    }


def make_flash_profile(root: Path, theme: str = "light") -> dict:
    """Seed a resumed AIL session plus unrelated progress; never copy user data."""
    from PIL import Image, ImageDraw
    from app.domain.models import ExamConfig, FeedbackMode
    from app.repositories.database import Database
    from app.services.data_scanner import DataScannerService
    from app.services.exam import ExamService
    from app.services.question_bank_updates import QuestionBankUpdateChecker

    profile = Path(tempfile.mkdtemp(prefix=f"flash-{theme}-", dir=root))
    for subject, amount in (("AIL303m", 8), ("CPV301", 2)):
        folder = profile / "DATA" / subject
        images = folder / "Selections_1_choose"
        images.mkdir(parents=True)
        for index in range(amount):
            image = Image.new("RGB", (720, 400), "white")
            ImageDraw.Draw(image).text((35, 70), f"{subject} - RELEASE QA - Question {index + 1}\n\nA. Option A\nB. Option B\nC. Option C\nD. Option D", fill="black")
            image.save(images / f"QA{index:02}.png")
        with (folder / "answers.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["image_name", "correct_answer"])
            writer.writerows((f"Selections_1_choose/QA{i:02}.png", "ABCD"[i % 4]) for i in range(amount))
    subjects = DataScannerService(profile / "DATA").scan()
    path = profile / "study_progress.sqlite3"
    database = Database(path)
    try:
        database.set_setting("data_dir", str(profile / "DATA"))
        database.set_setting("theme", theme)
        database.sync_questions([q for subject in subjects for q in subject.questions], [s.name for s in subjects])
        for subject in subjects:
            QuestionBankUpdateChecker(database, (0, 0.9, 0.25, 0.1)).check_subject(subject)
        ail = next(subject for subject in subjects if subject.name == "AIL303m")
        order = [q.id for q in ail.questions]
        session = database.create_flash_session("AIL303m", order)
        database.update_flash_position(session, 1, complete=False)
        database.rate_card(order[0], True)
        cram = database.create_cram_cycle("AIL303m", 17, [order])
        database.rate_cram_item(cram, order[0], False)
        cpv = next(subject for subject in subjects if subject.name == "CPV301")
        other = database.create_flash_session("CPV301", [q.id for q in cpv.questions])
        database.update_flash_position(other, 1, complete=False)
        database.rate_card(cpv.questions[0].id, False)
        exam = ExamService(database, [cpv.questions[0]], {cpv.questions[0].relative_path: "A"})
        attempt = exam.create_session(ExamConfig(
            subject="CPV301", categories=("Selections_1_choose",), question_count=1,
            duration_minutes=1, feedback_mode=FeedbackMode.DEFERRED,
        ))
        attempt.set_answer("A")
        attempt.submit()
    finally:
        database.close()
    return {
        "path": profile, "database": path, "session_id": session,
        "order": order, "initial_position": 1,
        "progress": progress_rows(path), "files": data_files(profile),
    }


def check_flash_profile(state: dict, ratings: list[bool]) -> None:
    """Only deliberate ratings/current cursor may change, never other history."""
    after = progress_rows(state["database"])
    before = state["progress"]
    for table in before.keys() - {"card_progress", "flash_sessions"}:
        assert after[table] == before[table], f"Unrelated {table} changed"
    original = {row["id"]: row for row in before["flash_sessions"]}
    current = {row["id"]: row for row in after["flash_sessions"]}
    assert original.keys() == current.keys(), "A session was recreated or deleted"
    for identifier, previous in original.items():
        actual = current[identifier].copy()
        if identifier == state["session_id"]:
            assert actual["current_position"] == state["initial_position"] + len(ratings)
            assert actual["status"] == "active"
            actual["current_position"] = previous["current_position"]
            actual["updated_at"] = previous["updated_at"]
        assert actual == previous, "Saved session identity/order/options changed"
    old_cards = {row["question_id"]: row for row in before["card_progress"]}
    cards = {row["question_id"]: row for row in after["card_progress"]}
    visited = state["order"][state["initial_position"]:state["initial_position"] + len(ratings)]
    assert cards.keys() == old_cards.keys() | set(visited), "Unexpected card progress changed"
    for question_id in old_cards.keys() - set(visited):
        assert cards[question_id] == old_cards[question_id]
    for question_id, known in zip(visited, ratings, strict=True):
        assert cards[question_id]["state"] == ("known" if known else "learning")
        assert cards[question_id]["review_count"] == old_cards.get(question_id, {}).get("review_count", 0) + 1
        assert cards[question_id]["last_reviewed_at"]
    assert data_files(state["path"]) == state["files"], "Question data/history files changed"


@contextmanager
def native_window(executable: Path, profile: Path, root: Path, label: str):
    """Drive only the process tree launched here, never another user's app."""
    import psutil
    from pywinauto import Desktop

    environment = os.environ.copy()
    environment.update(SRC_LEARNING_STATE_DIR=str(profile), QT_QPA_PLATFORM="windows")
    process = subprocess.Popen([str(executable.resolve())], env=environment, cwd=profile)
    main = None
    try:
        desktop = Desktop(backend="uia")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            assert process.poll() is None, "Flashcard EXE exited during startup"
            for pid in [process.pid, *[child.pid for child in psutil.Process(process.pid).children(recursive=True)]]:
                candidate = desktop.window(title="SRC LEARNING", process=pid)
                if candidate.exists(timeout=0.2):
                    main = candidate
                    break
            if main is not None:
                break
            time.sleep(0.2)
        assert main is not None, "No real Flashcard EXE window"
        main.wait("visible enabled ready", timeout=30)
        yield process, main
    except Exception:
        if main is not None:
            try:
                main.capture_as_image().save(root / f"flashcard-{label}-failure.png")
                main.print_control_identifiers(filename=str(root / f"flashcard-{label}-controls.txt"))
            except Exception:
                pass
        raise
    finally:
        if process.poll() is None:
            for child in psutil.Process(process.pid).children(recursive=True):
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            process.terminate()
            process.wait(timeout=15)


def native_space(process) -> dict:
    """Send a physical Space to the real recipient, without refocusing a widget."""
    import psutil
    from pywinauto import keyboard
    from pywinauto.uia_defines import IUIA

    element = IUIA().get_focused_element()
    pids = {process.pid, *[child.pid for child in psutil.Process(process.pid).children(recursive=True)]}
    assert element.CurrentProcessId in pids, "Refusing keyboard input outside the QA EXE"
    focus = {"process_id": element.CurrentProcessId, "name": element.CurrentName, "class": element.CurrentClassName}
    keyboard.send_keys("{SPACE}")
    return focus


def native_open_flashcards(main, position: int) -> None:
    # Exact accessible names come from SubjectCard and StudyModeCard, not pixels.
    subject = main.child_window(title="Môn học AIL303m, 8 câu hỏi")
    subject.wait("visible enabled ready", timeout=30)
    subject.click_input()
    mode = main.child_window(title="Mở chế độ Học bình thường")
    mode.wait("visible enabled ready", timeout=20)
    mode.click_input()
    main.child_window(title=f"Câu {position + 1}/8", control_type="Text").wait("visible", timeout=20)
    main.child_window(title="Đã thuộc", control_type="Button").wait("visible", timeout=10)


def windows_flashcard_qa(root: Path, executable: Path) -> list[dict]:
    if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("Flashcard native QA requires the isolated GitHub Windows runner")
    from pywinauto.uia_defines import IUIA

    cases = []
    for theme in ("light", "dark"):
        state = make_flash_profile(root, theme)
        ratings = [True, False, True]
        focus_trace = []
        print(f"Flashcard EXE QA: {theme}, resume existing session {state['session_id']}", flush=True)
        with native_window(executable, state["path"], root, f"{theme}-study") as (process, main):
            native_open_flashcards(main, state["initial_position"])
            for index, known in enumerate(ratings):
                focus_trace.append(native_space(process))
                main.child_window(title="Đã thuộc", control_type="Button").wait("enabled", timeout=10)
                main.child_window(title="Đã thuộc" if known else "Chưa thuộc", control_type="Button").click_input()
                position = state["initial_position"] + index + 1
                main.child_window(title=f"Câu {position + 1}/8", control_type="Text").wait("visible", timeout=10)
                check_flash_profile(state, ratings[:index + 1])
            # Deliberately focus the Home logo without clicking it. Space must
            # remain owned by the active Flash Cards page, even in this state.
            home = main.child_window(title="Về màn hình chính — SRC Learning", control_type="Button")
            home.set_focus()
            assert IUIA().get_focused_element().CurrentName == "Về màn hình chính — SRC Learning"
            focus_trace.append(native_space(process))
            main.child_window(title="Đã thuộc", control_type="Button").wait("enabled", timeout=10)
            main.child_window(title="Câu 5/8", control_type="Text").wait("visible", timeout=10)
            main.capture_as_image().save(root / f"flashcard-{theme}-study.png")
            check_flash_profile(state, ratings)
            main.close()
            assert process.wait(timeout=30) == 0, "Study EXE did not exit cleanly"
        after_study = progress_rows(state["database"])
        # A second real process must resume the same persisted session/cursor.
        with native_window(executable, state["path"], root, f"{theme}-resume") as (process, main):
            native_open_flashcards(main, 4)
            focus_trace.append(native_space(process))
            main.child_window(title="Đã thuộc", control_type="Button").wait("enabled", timeout=10)
            main.child_window(title="Câu 5/8", control_type="Text").wait("visible", timeout=10)
            main.capture_as_image().save(root / f"flashcard-{theme}-resume.png")
            main.close()
            assert process.wait(timeout=30) == 0, "Resumed EXE did not exit cleanly"
        check_flash_profile(state, ratings)
        assert progress_rows(state["database"]) == after_study, "Reopening reset or rewrote progress"
        cases.append({
            "scenario": theme, "status": "PASS", "ratings": ratings,
            "initial_position": 1, "final_position": 4,
            "resumed_session_id": state["session_id"],
            "mouse_keyboard_flow_passed": True, "header_focus_guard_passed": True,
            "session_resume_passed": True, "unrelated_progress_preserved": True,
            "question_order_preserved": True, "clean_exit": True,
            "focus_before_space": focus_trace,
        })
        print(f"Flashcard EXE QA: {theme} PASS, same session/order, cursor 2 -> 5/8, resume PASS", flush=True)
    return cases


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    args = parser.parse_args()
    root = marked_workspace(args.workdir)
    os.environ["SRC_LEARNING_STATE_DIR"] = str(root / "unused-flashcard-profile")
    cases = windows_flashcard_qa(root, args.exe)
    report = {
        "status": "PASS", "platform": sys.platform, "mode": "windows",
        "commit": os.environ.get("GITHUB_SHA"), "cases": cases,
        "executable_sha256": digest(args.exe),
    }
    (root / "flashcard-windows-gui-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
