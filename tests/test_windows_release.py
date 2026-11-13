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
    catalog = {"CPV301": cpv}
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
