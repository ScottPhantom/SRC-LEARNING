"""Package only the Windows EXE that passed native GUI QA, with exact provenance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def embedded_catalog(executable: Path) -> dict:
    from PyInstaller.archive.readers import CArchiveReader

    reader = CArchiveReader(str(executable))
    names = [name for name in reader.toc if name.replace("\\", "/").endswith("app/resources/data_manifest.json")]
    if len(names) != 1:
        raise ValueError("Cannot identify the one embedded DSS manifest in this EXE")
    manifest = json.loads(reader.extract(names[0]))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported embedded DSS catalog schema")
    return {item["subject"]: item for item in manifest["packages"] if item.get("enabled")}


def verify_pe_x64(executable: Path) -> None:
    with executable.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("Not a Windows PE executable")
        stream.seek(0x3C)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        if stream.read(4) != b"PE\x00\x00" or stream.read(2) != b"\x64\x86":
            raise ValueError("The release executable is not Windows x64")


def verify_ssg105t_gui(qa: Path, catalog: dict, commit: str, executable_digest: str) -> dict:
    reference_path = Path(__file__).parent / "fixtures/ssg105t_v1_reference.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    expected = reference["approved_packages"]
    if any(catalog.get(subject) != package for subject, package in expected.items()):
        raise ValueError("SSG105t catalog differs from the approved DSS packages")
    reports = {}
    for mode in ("qt", "windows"):
        report = json.loads((qa / f"ssg105t-{mode}-gui-report.json").read_text(encoding="utf-8"))
        cases = report.get("cases", [])
        if (
            report.get("status") != "PASS" or report.get("mode") != mode
            or report.get("commit") != commit or report.get("packages") != expected
            or report.get("reference_sha256") != sha256(reference_path)
            or len(cases) != 3 or {case.get("scenario") for case in cases} != {"fresh", "upgrade", "cancel-active"}
        ):
            raise ValueError("Incomplete or stale SSG105t GUI release gate")
        if mode == "windows" and (report.get("platform") != "win32" or report.get("executable_sha256") != executable_digest):
            raise ValueError("SSG105t native evidence belongs to a different Windows EXE")
        for case in cases:
            cancelled = case["scenario"] == "cancel-active"
            required = ["progress_and_history_preserved", "old_ssg105_unchanged", "ail_sessions_preserved", "original_158_preserved", "sqlite_integrity_ok"]
            required.append("active_target_cancel_preserved" if cancelled else "repeat_import_no_extra_version")
            if mode == "windows":
                required.extend(("clean_exit", "reopen_preserved", "physical_mouse_gui"))
            if (
                case.get("status") != "PASS" or any(case.get(field) is not True for field in required)
                or case.get("bank_version") != (2 if case["scenario"] == "upgrade" else 1)
                or case.get("question_count") != (158 if cancelled else 369)
            ):
                raise ValueError("SSG105t GUI did not preserve progress, history, sessions or old SSG105")
        reports[mode] = report
    return reports


def package(executable: Path, qa: Path, archive: Path) -> dict:
    verify_pe_x64(executable)
    if archive.exists():
        raise ValueError(f"Refusing to overwrite an existing release: {archive}")
    metadata = json.loads((qa / "metadata.json").read_text(encoding="utf-8"))
    qt_report = json.loads((qa / "qt-gui-report.json").read_text(encoding="utf-8"))
    windows_report = json.loads((qa / "windows-gui-report.json").read_text(encoding="utf-8"))
    executable_digest = sha256(executable)
    for report, scenarios in ((qt_report, {"legacy", "add", "fresh"}), (windows_report, {"legacy", "add"})):
        if report.get("status") != "PASS" or {case["scenario"] for case in report["cases"]} != scenarios:
            raise ValueError("Incomplete GUI release gate")
        if any(case.get("status") != "PASS" or not case.get("preserved_progress_and_two_ail_sessions") for case in report["cases"]):
            raise ValueError("GUI QA did not preserve progress and AIL sessions")
        if report["cpv"] != metadata["cpv"]:
            raise ValueError("GUI QA used different CPV metadata")
        if os.environ.get("GITHUB_SHA") and report.get("commit") != os.environ["GITHUB_SHA"]:
            raise ValueError("GUI QA belongs to a different commit")
    if windows_report.get("executable_sha256") != executable_digest:
        raise ValueError("The executable changed after native GUI QA")
    if any(not case.get("clean_exit") for case in windows_report["cases"]):
        raise ValueError("Native GUI QA did not exit cleanly")
    flash_report = json.loads((qa / "flashcard-windows-gui-report.json").read_text(encoding="utf-8"))
    if (
        flash_report.get("status") != "PASS" or flash_report.get("platform") != "win32"
        or flash_report.get("mode") != "windows"
        or flash_report.get("commit") != windows_report.get("commit")
        or flash_report.get("executable_sha256") != executable_digest
        or {case["scenario"] for case in flash_report.get("cases", [])} != {"light", "dark"}
    ):
        raise ValueError("Incomplete or mismatched native Flashcard GUI release gate")
    for case in flash_report["cases"]:
        if case.get("status") != "PASS" or any(not case.get(field) for field in (
            "mouse_keyboard_flow_passed", "header_focus_guard_passed", "session_resume_passed",
            "unrelated_progress_preserved", "question_order_preserved", "clean_exit",
        )):
            raise ValueError("Flashcard GUI QA did not preserve sessions or pass mouse/keyboard input")
    actual = embedded_catalog(executable)
    if actual != metadata["catalog"]:
        raise ValueError("Embedded EXE catalog differs from the verified DSS metadata")
    ssg_reports = verify_ssg105t_gui(qa, actual, windows_report["commit"], executable_digest)

    report = {
        "commit": os.environ.get("GITHUB_SHA"), "architecture": "Windows x64",
        "executable": executable.name, "executable_sha256": executable_digest,
        "catalog": actual, "qt_gui_cases": qt_report["cases"],
        "native_exe_gui_cases": windows_report["cases"],
        "native_flashcard_gui_cases": flash_report["cases"],
        "source_ssg105t_gui_cases": ssg_reports["qt"]["cases"],
        "native_ssg105t_gui_cases": ssg_reports["windows"]["cases"],
        "ssg105t_reference_sha256": ssg_reports["windows"]["reference_sha256"],
        "data_included": False, "authenticode_signed": False,
    }
    codes = "\n".join(f"- {name}: {item['file_id']}" for name, item in sorted(actual.items()))
    readme = f"""SRC Learning — Windows x64
Commit: {report['commit']}

1. Thoát app cũ. Giải nén ZIP vào thư mục mới, không chạy EXE ngay trong ZIP.
2. Mở LuyenThiHinhAnh.exe. Không cần cài Python hoặc chạy quyền Administrator.
3. Giữ nguyên %USERPROFILE%\\.luyen_thi_hinh_anh: đây là dữ liệu, tiến độ và phiên học.
   Không xóa môn hoặc database để sửa lỗi version. Chỉ thay ứng dụng.
4. Dùng nút + để cài/cập nhật từng môn. Cập nhật CPV không cần cập nhật AIL;
   có thể giữ nguyên phiên AIL đang học. Gói ZIP ứng dụng không chứa DATA/database.

Mã Google Drive của {len(actual)} gói đang bật:
{codes}

SSG105t là gói riêng 369 câu, không ghi đè SSG105 gộp 456 câu. Hồ sơ đã cài
SSG105t 158 câu có thể cập nhật qua nút + với cùng mã, chọn Xác minh và thay thế.
Giữ tiến độ, lịch sử và 158 câu cũ; bổ sung 211 câu. Nếu chính SSG105t có phiên
đang học, chọn Giữ phiên và hủy thao tác để tiếp tục học, rồi cập nhật khi đã
kết thúc phiên. Không chọn hủy phiên nếu vẫn muốn tiếp tục phiên đó.

Bản này sửa đồng bộ manifest–SQLite và phục hồi metadata bị thiếu từ snapshot
hợp lệ, không xóa tiến độ hay phiên học. Version mới được tạo khi nội dung đổi;
tải lại cùng nội dung không tạo thêm version. Lịch sử mâu thuẫn hoặc snapshot
hỏng vẫn bị chặn để bảo vệ dữ liệu, không tự đặt lại version.

Flash Cards: Space luôn hiện/ẩn đáp án của màn hình học đang mở, không bấm nhầm
logo về Home sau khi chọn Đã thuộc/Chưa thuộc. Bản EXE đã qua kiểm thử chuột +
bàn phím ở giao diện sáng/tối và tiếp tục đúng phiên học sau khi mở lại.

EXE chưa ký số Authenticode. Chỉ dùng bản tải từ Release chính thức và đối chiếu
SHA-256; không tắt Defender/SmartScreen toàn hệ thống để xử lý cảnh báo.
"""
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(executable, executable.name)
        bundle.writestr("README_VI.txt", readme.encode("utf-8-sig"))
        bundle.writestr("release-info.json", json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("Release ZIP CRC verification failed")
        if hashlib.sha256(bundle.read(executable.name)).hexdigest() != executable_digest:
            raise ValueError("Release ZIP contains a different executable")
    report["archive"] = archive.name
    report["archive_sha256"] = sha256(archive)
    report["archive_size"] = archive.stat().st_size
    archive.with_suffix(archive.suffix + ".sha256").write_text(f"{report['archive_sha256']}  {archive.name}\n", encoding="utf-8")
    (archive.parent / "windows-release-info.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    for output_stream in (sys.stdout, sys.stderr):
        if output_stream is not None and hasattr(output_stream, "reconfigure"):
            output_stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--qa-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.exe, args.qa_dir, args.archive), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
