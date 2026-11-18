from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from PIL import Image

from app.repositories.database import Database
from tools import ssg105t_release_qa as qa


@pytest.fixture
def sources(tmp_path, monkeypatch):
    folders = {}
    for name, count in (("SSG105t", 369), ("SSG105", 456)):
        folder = tmp_path / "sources" / name
        images = folder / "Selections_1_choose"
        images.mkdir(parents=True)
        for index in range(count):
            Image.new("RGB", (32, 24), "white").save(images / f"Q{index:03}.png")
        with (folder / "answers.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["image_name", "correct_answer"])
            writer.writerows((f"Selections_1_choose/Q{i:03}.png", "ABCD"[i % 4]) for i in range(count))
        with (folder / "question_metadata.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["image_name", "option_letters"])
            writer.writerows((f"Selections_1_choose/Q{i:03}.png", "ABCDE" if i % 2 else "ABCD") for i in range(count))
        folders[name] = str(folder)
    paths = [f"Selections_1_choose/Q{i:03}.png" for i in range(158)]
    reference = {"paths": paths, "fingerprint_sha256": qa.fingerprint(Path(folders["SSG105t"]), paths)}
    ref_path = tmp_path / "reference.json"
    ref_path.write_text(json.dumps(reference))
    monkeypatch.setattr(qa, "REFERENCE", ref_path)
    return {"sources": folders, "reference_sha256": qa.digest(ref_path)}


def test_baseline_is_exactly_158_and_preserves_saved_progress_and_real_course_identity(tmp_path, sources):
    state = qa.make_profile(tmp_path, sources, "upgrade", "unit")
    assert state["baseline"] == "v1-content-reconstructed-and-fingerprint-verified"
    assert all(qa.check_preserved(state, 1, 158).values())
    database = Database(state["database"])
    try:
        assert database.active_flash_session("SSG105t") is None
        for subject in ("SSG105", "AIL303m"):
            assert database.active_flash_session(subject) is not None
            assert database.active_cram_cycle(subject) is not None
    finally:
        database.close()


@pytest.mark.parametrize("fault", ["rating", "history", "ssg_session", "ail_session", "old_ssg_file", "original_image", "original_key", "original_choices"])
def test_ssg105t_preservation_gate_detects_every_protected_state_mutation(tmp_path, sources, fault):
    state = qa.make_profile(tmp_path, sources, "cancel-active", "unit")
    if fault in {"old_ssg_file", "original_image"}:
        folder = "SSG105" if fault == "old_ssg_file" else "SSG105t"
        with next((state["path"] / "DATA" / folder).rglob("*.png")).open("ab") as stream:
            stream.write(b"changed")
    elif fault in {"original_key", "original_choices"}:
        path = state["path"] / "DATA/SSG105t" / ("answers.csv" if fault == "original_key" else "question_metadata.csv")
        content = path.read_text(encoding="utf-8-sig")
        path.write_text(content.replace("Q000.png,A", "Q000.png,B", 1), encoding="utf-8-sig")
    else:
        database = Database(state["database"])
        try:
            if fault.endswith("session"):
                database.delete_active_flash_session("SSG105" if fault == "ssg_session" else "AIL303m")
            elif fault == "history":
                with database.transaction() as connection:
                    connection.execute("DELETE FROM exam_attempts WHERE subject='SSG105t'")
            else:
                identifier = state["progress"]["card_progress"][0]["question_id"]
                database.rate_card(identifier, False)
        finally:
            database.close()
    with pytest.raises(AssertionError):
        qa.check_preserved(state, 1, 158)


def test_ssg105t_native_gate_refuses_to_control_a_non_runner_desktop(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(ValueError, match="isolated GitHub Windows runner"):
        qa.windows_qa(tmp_path, {}, tmp_path / "not-launched.exe")
