"""Package only the Windows EXE that passed native GUI QA, with exact provenance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
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
    actual = embedded_catalog(executable)
    if actual != metadata["catalog"]:
        raise ValueError("Embedded EXE catalog differs from the verified DSS metadata")

    report = {
        "commit": os.environ.get("GITHUB_SHA"), "architecture": "Windows x64",
        "executable": executable.name, "executable_sha256": executable_digest,
        "catalog": actual, "qt_gui_cases": qt_report["cases"],
        "native_exe_gui_cases": windows_report["cases"],
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

Mã Google Drive của 4 môn đang bật:
{codes}

Bản này sửa đồng bộ manifest–SQLite và phục hồi metadata bị thiếu từ snapshot
hợp lệ, không xóa tiến độ hay phiên học. Version mới được tạo khi nội dung đổi;
tải lại cùng nội dung không tạo thêm version. Lịch sử mâu thuẫn hoặc snapshot
hỏng vẫn bị chặn để bảo vệ dữ liệu, không tự đặt lại version.

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--qa-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.exe, args.qa_dir, args.archive), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
