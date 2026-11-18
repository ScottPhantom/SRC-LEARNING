from __future__ import annotations

import json
import struct
import zipfile

import pytest

from tools import windows_release


@pytest.fixture
def release_inputs(tmp_path, monkeypatch):
    executable = tmp_path / "LuyenThiHinhAnh.exe"
    header = bytearray(256)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 128)
    header[128:134] = b"PE\x00\x00\x64\x86"
    executable.write_bytes(header)
    qa = tmp_path / "qa"
    qa.mkdir()
    cpv = {"subject": "CPV301", "file_id": "approved-cpv-code"}
    reference_path = windows_release.Path(windows_release.__file__).parent / "fixtures/ssg105t_v1_reference.json"
    reference = json.loads(reference_path.read_text())
    catalog = {"CPV301": cpv, **reference["approved_packages"]}
    monkeypatch.setattr(windows_release, "embedded_catalog", lambda _exe: catalog)
    monkeypatch.setenv("GITHUB_SHA", "test-commit")
    (qa / "metadata.json").write_text(json.dumps({"cpv": cpv, "catalog": catalog}))
    for mode, scenarios in (("qt", ("legacy", "add", "fresh")), ("windows", ("legacy", "add"))):
        report = {
            "status": "PASS", "commit": "test-commit", "cpv": cpv,
            "executable_sha256": windows_release.sha256(executable),
            "cases": [{"scenario": scenario, "status": "PASS", "preserved_progress_and_two_ail_sessions": True, "clean_exit": True} for scenario in scenarios],
        }
        (qa / f"{mode}-gui-report.json").write_text(json.dumps(report))
    flash = {
        "status": "PASS", "platform": "win32", "mode": "windows", "commit": "test-commit",
        "executable_sha256": windows_release.sha256(executable),
        "cases": [{
            "scenario": theme, "status": "PASS", "mouse_keyboard_flow_passed": True,
            "header_focus_guard_passed": True, "session_resume_passed": True,
            "unrelated_progress_preserved": True, "question_order_preserved": True, "clean_exit": True,
        } for theme in ("light", "dark")],
    }
    (qa / "flashcard-windows-gui-report.json").write_text(json.dumps(flash))
    for mode in ("qt", "windows"):
        report = {
            "status": "PASS", "mode": mode, "platform": "win32", "commit": "test-commit",
            "executable_sha256": windows_release.sha256(executable),
            "packages": reference["approved_packages"], "reference_sha256": windows_release.sha256(reference_path),
            "cases": [{
                "scenario": scenario, "status": "PASS", "bank_version": 2 if scenario == "upgrade" else 1,
                "question_count": 158 if scenario == "cancel-active" else 369,
                "progress_and_history_preserved": True, "old_ssg105_unchanged": True,
                "ail_sessions_preserved": True, "original_158_preserved": True, "sqlite_integrity_ok": True,
                "repeat_import_no_extra_version": scenario != "cancel-active",
                "active_target_cancel_preserved": scenario == "cancel-active",
                "clean_exit": True, "reopen_preserved": True, "physical_mouse_gui": True,
            } for scenario in ("fresh", "upgrade", "cancel-active")],
        }
        (qa / f"ssg105t-{mode}-gui-report.json").write_text(json.dumps(report))
    return executable, qa, tmp_path / "release.zip"


def test_package_contains_only_the_verified_exe_instructions_and_provenance(release_inputs):
    executable, qa, archive = release_inputs
    result = windows_release.package(executable, qa, archive)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert set(bundle.namelist()) == {executable.name, "README_VI.txt", "release-info.json"}
        assert bundle.read(executable.name) == executable.read_bytes()
        assert "approved-cpv-code" in bundle.read("README_VI.txt").decode("utf-8-sig")
    assert result["archive_sha256"] == windows_release.sha256(archive)
    assert archive.with_suffix(".zip.sha256").is_file()


def test_package_rejects_an_exe_changed_after_native_gui_qa(release_inputs):
    executable, qa, archive = release_inputs
    with executable.open("ab") as stream:
        stream.write(b"changed after QA")
    with pytest.raises(ValueError, match="changed after native"):
        windows_release.package(executable, qa, archive)
    assert not archive.exists()


def test_package_rejects_missing_native_gui_scenarios(release_inputs):
    executable, qa, archive = release_inputs
    path = qa / "windows-gui-report.json"
    report = json.loads(path.read_text())
    report["cases"].pop()
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="Incomplete GUI"):
        windows_release.package(executable, qa, archive)


def test_package_rejects_stale_embedded_dss_catalog(release_inputs, monkeypatch):
    executable, qa, archive = release_inputs
    monkeypatch.setattr(windows_release, "embedded_catalog", lambda _exe: {})
    with pytest.raises(ValueError, match="Embedded EXE catalog"):
        windows_release.package(executable, qa, archive)


def test_package_rejects_a_different_commit(release_inputs, monkeypatch):
    executable, qa, archive = release_inputs
    monkeypatch.setenv("GITHUB_SHA", "different-commit")
    with pytest.raises(ValueError, match="different commit"):
        windows_release.package(executable, qa, archive)


def test_rejects_non_x64_windows_executable(release_inputs):
    executable, _qa, _archive = release_inputs
    with executable.open("r+b") as stream:
        stream.seek(132)
        stream.write(b"\x4c\x01")  # PE i386, not AMD64.
    with pytest.raises(ValueError, match="not Windows x64"):
        windows_release.verify_pe_x64(executable)


@pytest.mark.parametrize("fault", ["missing_case", "progress", "resume", "keyboard", "commit", "hash", "platform"])
def test_package_requires_matching_native_flashcard_evidence(release_inputs, fault):
    executable, qa, archive = release_inputs
    path = qa / "flashcard-windows-gui-report.json"
    report = json.loads(path.read_text())
    if fault == "missing_case":
        report["cases"].pop()
    elif fault in {"progress", "resume", "keyboard"}:
        field = {"progress": "unrelated_progress_preserved", "resume": "session_resume_passed", "keyboard": "mouse_keyboard_flow_passed"}[fault]
        report["cases"][0][field] = False
    else:
        field = {"commit": "commit", "hash": "executable_sha256", "platform": "platform"}[fault]
        report[field] = "incorrect-evidence"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="Flashcard"):
        windows_release.package(executable, qa, archive)
    assert not archive.exists()


@pytest.mark.parametrize("mode", ["qt", "windows"])
@pytest.mark.parametrize("fault", ["missing_case", "progress", "old_ssg105", "cancel", "repeat", "count", "version", "commit", "reference", "package", "hash", "reopen"])
def test_package_requires_fresh_and_upgrade_ssg105t_gui_evidence(release_inputs, mode, fault):
    if mode == "qt" and fault in {"hash", "reopen"}:
        pytest.skip("Native EXE-only evidence")
    executable, qa, archive = release_inputs
    path = qa / f"ssg105t-{mode}-gui-report.json"
    report = json.loads(path.read_text())
    if fault == "missing_case":
        report["cases"].pop()
    elif fault in {"progress", "old_ssg105", "repeat", "reopen"}:
        field = {"progress": "progress_and_history_preserved", "old_ssg105": "old_ssg105_unchanged", "repeat": "repeat_import_no_extra_version", "reopen": "reopen_preserved"}[fault]
        report["cases"][0][field] = False
    elif fault == "cancel":
        report["cases"][2]["active_target_cancel_preserved"] = False
    elif fault in {"count", "version"}:
        report["cases"][1]["question_count" if fault == "count" else "bank_version"] = 999
    elif fault == "package":
        report["packages"]["SSG105t"]["sha256"] = "wrong"
    else:
        report[{"commit": "commit", "reference": "reference_sha256", "hash": "executable_sha256"}[fault]] = "wrong"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="SSG105t"):
        windows_release.package(executable, qa, archive)
    assert not archive.exists()
