from __future__ import annotations

import csv
import hashlib
import os
import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app import config
from app.services.data_package_installer import (
    DataPackageCatalog,
    DataPackageError,
    DataPackageInstaller,
    DataPackageSpec,
    UnknownPackageCodeError,
)
from app.services.data_scanner import DataScannerService
from app.services.package_catalog_source import PackageCatalogSource
from app.services.subject_management import SubjectManagementError, SubjectManager


def make_subject_archive(root: Path, subject: str = "AIL303m") -> Path:
    source = root / "source" / "DATA" / subject
    image_path = source / "Selections_1_choose" / "Câu 1.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (120, 80), "white").save(image_path)
    with (source / "answers.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["image_name", "correct_answer"])
        writer.writerow(["Selections_1_choose/Câu 1.png", "A"])
    archive = root / f"{subject}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(root / "source"))
    return archive


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def installer_for(archive: Path, subject: str = "AIL303m") -> DataPackageInstaller:
    file_id = "approved-drive-file-id"
    package = DataPackageSpec(
        subject=subject,
        file_id=file_id,
        sha256=sha256(archive),
        archive_size=archive.stat().st_size,
    )

    def copy_download(
        requested_id: str, output: Path, _size: int, progress
    ) -> Path:
        assert requested_id == file_id
        progress("download", 50, "Đang tải")
        shutil.copy2(archive, output)
        progress("download", 100, "Đã tải")
        return output

    return DataPackageInstaller(DataPackageCatalog([package]), copy_download)


def test_catalog_accepts_file_id_and_share_url() -> None:
    package = DataPackageSpec(
        subject="AIL303m",
        file_id="1r82uwHDR7LVfpVv74W75OZ6xWh-2odrP",
        sha256="a" * 64,
        archive_size=100,
    )
    catalog = DataPackageCatalog([package])

    assert catalog.resolve(package.file_id) == package
    assert catalog.resolve(
        f"https://drive.google.com/file/d/{package.file_id}/view"
    ) == package
    with pytest.raises(UnknownPackageCodeError):
        catalog.resolve("not-approved-file-id")


def sheet_csv(*rows: str) -> bytes:
    header = "Môn,Google file ID,Số câu,SHA-256 ZIP,Kích thước (byte),App manifest"
    return (header + "\n" + "\n".join(rows) + "\n").encode("utf-8-sig")


def test_sheet_catalog_only_accepts_enabled_rows() -> None:
    content = sheet_csv(
        f"AIL303m,approved-drive-file-id,154,{'a' * 64},18056033,Đã bật",
        f"CPV301,other-drive-file-id,89,{'b' * 64},21423181,Chưa khai báo",
    )
    catalog = DataPackageCatalog.from_sheet_csv(content)
    assert catalog.resolve("approved-drive-file-id").expected_questions == 154
    with pytest.raises(UnknownPackageCodeError):
        catalog.resolve("other-drive-file-id")


@pytest.mark.parametrize("bad_row", [
    f"../escape,approved-drive-file-id,154,{'a' * 64},100,Đã bật",
    "AIL303m,approved-drive-file-id,154,invalid,100,Đã bật",
    f"AIL303m,approved-drive-file-id,154,{'a' * 64},0,Đã bật",
])
def test_sheet_catalog_rejects_bad_approved_rows(bad_row: str) -> None:
    with pytest.raises(DataPackageError, match="Danh mục"):
        DataPackageCatalog.from_sheet_csv(sheet_csv(bad_row))


def test_sheet_catalog_rejects_duplicate_ids() -> None:
    content = sheet_csv(
        f"AIL303m,approved-drive-file-id,154,{'a' * 64},100,Đã bật",
        f"CPV301,approved-drive-file-id,89,{'b' * 64},200,Đã bật",
    )
    with pytest.raises(DataPackageError, match="trùng lặp"):
        DataPackageCatalog.from_sheet_csv(content)


def test_catalog_source_caches_valid_sheet_and_falls_back_offline(tmp_path: Path) -> None:
    content = sheet_csv(
        f"CPV301,approved-drive-file-id,89,{'b' * 64},21423181,Đã bật"
    )
    url = "https://docs.google.com/spreadsheets/d/e/example/pub?gid=105&output=csv"
    cache = tmp_path / "catalog.csv"
    online = PackageCatalogSource(url, cache, fetch=lambda _url: content).load()
    assert online.source == "Google Sheets"
    assert online.catalog.resolve("approved-drive-file-id").subject == "CPV301"
    assert cache.read_bytes() == content

    def offline(_url: str) -> bytes:
        raise OSError("offline")

    fallback = PackageCatalogSource(url, cache, fetch=offline).load()
    assert fallback.source == "bộ nhớ đệm"
    assert fallback.warning
    assert fallback.catalog.resolve("approved-drive-file-id").subject == "CPV301"


def test_installer_rejects_question_count_mismatch_before_writing(tmp_path: Path) -> None:
    archive = make_subject_archive(tmp_path)
    installer = installer_for(archive)
    original = installer.catalog.resolve("approved-drive-file-id")
    installer.catalog = DataPackageCatalog([
        DataPackageSpec(
            original.subject, original.file_id, original.sha256,
            original.archive_size, expected_questions=2,
        )
    ])
    destination = tmp_path / "DATA"
    with pytest.raises(DataPackageError, match="Số câu"):
        installer.install(original.file_id, destination)
    assert not (destination / original.subject).exists()


def test_installer_rejects_archive_size_mismatch(tmp_path: Path) -> None:
    archive = make_subject_archive(tmp_path)
    installer = installer_for(archive)
    original = installer.catalog.resolve("approved-drive-file-id")
    installer.catalog = DataPackageCatalog([
        DataPackageSpec(
            original.subject, original.file_id, original.sha256,
            original.archive_size + 1,
        )
    ])
    destination = tmp_path / "DATA"
    with pytest.raises(DataPackageError, match="Kích thước"):
        installer.install(original.file_id, destination)
    assert not (destination / original.subject).exists()


def test_invalid_sheet_does_not_replace_last_good_cache(tmp_path: Path) -> None:
    url = "https://docs.google.com/spreadsheets/d/e/example/pub?gid=105&output=csv"
    cache = tmp_path / "catalog.csv"
    good = sheet_csv(f"AIL303m,approved-drive-file-id,154,{'a' * 64},100,Đã bật")
    cache.write_bytes(good)
    result = PackageCatalogSource(url, cache, fetch=lambda _url: b"<html>login</html>").load()
    assert result.source == "bộ nhớ đệm"
    assert cache.read_bytes() == good


def test_catalog_source_rejects_other_sheet_tabs(tmp_path: Path) -> None:
    called = False

    def fetch(_url: str) -> bytes:
        nonlocal called
        called = True
        return b""

    source = PackageCatalogSource(
        "https://docs.google.com/spreadsheets/d/e/example/pub?gid=0&output=csv",
        tmp_path / "catalog.csv",
        fetch=fetch,
    )
    result = source.load()
    assert result.source == "bản đóng gói"
    assert not called
    assert "GOOGLE_IDS" in result.warning


def test_catalog_url_can_be_supplied_next_to_existing_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://docs.google.com/spreadsheets/d/e/example/pub?gid=105&output=csv"
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.delenv("SRC_LEARNING_CATALOG_CSV_URL", raising=False)
    (tmp_path / "catalog_source_url.txt").write_text(url + "\n", encoding="utf-8")
    assert config.catalog_csv_url() == url

    monkeypatch.setenv("SRC_LEARNING_CATALOG_CSV_URL", "  " + url + "  ")
    assert config.catalog_csv_url() == url

    monkeypatch.delenv("SRC_LEARNING_CATALOG_CSV_URL")
    (tmp_path / "catalog_source_url.txt").write_text("\n", encoding="utf-8")
    assert config.catalog_csv_url() == config.CATALOG_CSV_URL


def test_default_catalog_url_is_published_google_ids_csv() -> None:
    assert "/spreadsheets/d/e/" in config.CATALOG_CSV_URL
    PackageCatalogSource._validate_url(config.CATALOG_CSV_URL)
    assert "gid=105" in config.CATALOG_CSV_URL
    assert "output=csv" in config.CATALOG_CSV_URL


def test_missing_catalog_url_explains_bundled_fallback(tmp_path: Path) -> None:
    result = PackageCatalogSource("", tmp_path / "catalog.csv").load()
    assert result.source == "bản đóng gói"
    assert "chưa được cấu hình" in result.warning


def test_installer_validates_and_atomically_installs_subject(tmp_path: Path) -> None:
    archive = make_subject_archive(tmp_path)
    installer = installer_for(archive)
    progress: list[tuple[str, int, str]] = []

    result = installer.install(
        "approved-drive-file-id",
        tmp_path / "app" / "DATA",
        progress=lambda stage, percent, message: progress.append(
            (stage, percent, message)
        ),
    )

    assert result.subject == "AIL303m"
    assert result.question_count == 1
    assert (result.destination / "answers.csv").is_file()
    assert (result.destination / "Selections_1_choose" / "Câu 1.png").is_file()
    assert progress[-1][:2] == ("complete", 100)


def test_installer_keeps_existing_subject_when_checksum_fails(tmp_path: Path) -> None:
    archive = make_subject_archive(tmp_path)
    installer = installer_for(archive)
    package = installer.catalog.resolve("approved-drive-file-id")
    installer.catalog = DataPackageCatalog(
        [
            DataPackageSpec(
                subject=package.subject,
                file_id=package.file_id,
                sha256="0" * 64,
                archive_size=package.archive_size,
            )
        ]
    )
    destination = tmp_path / "app" / "DATA" / "AIL303m"
    destination.mkdir(parents=True)
    marker = destination / "keep.txt"
    marker.write_text("original", encoding="utf-8")

    with pytest.raises(DataPackageError, match="SHA-256"):
        installer.install(
            "approved-drive-file-id",
            destination.parent,
            replace_existing=True,
        )

    assert marker.read_text(encoding="utf-8") == "original"


def test_safe_extract_rejects_zip_slip(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.txt", "unsafe")

    with pytest.raises(DataPackageError, match="không an toàn"):
        DataPackageInstaller._safe_extract(
            archive, tmp_path / "extract", lambda *_args: None
        )

    assert not (tmp_path / "outside.txt").exists()


def test_subject_remove_moves_exact_directory_and_keeps_neighbor(tmp_path: Path) -> None:
    data = tmp_path / "DATA"
    subject = data / "AIL303m"
    neighbor = data / "OTHER101"
    subject.mkdir(parents=True)
    neighbor.mkdir()
    (subject / "marker.txt").write_text("old", encoding="utf-8")
    backup = SubjectManager(data).remove("AIL303m")
    assert not subject.exists()
    assert (backup / "marker.txt").read_text(encoding="utf-8") == "old"
    assert neighbor.is_dir() and data.is_dir()
    assert backup.parent == tmp_path / ".src-learning-recovery"


@pytest.mark.parametrize("name", ["..", "../OTHER101", "AIL303m/..", "/tmp/AIL303m", ".hidden"])
def test_subject_remove_rejects_path_attack(tmp_path: Path, name: str) -> None:
    data = tmp_path / "DATA"
    (data / "AIL303m").mkdir(parents=True)
    with pytest.raises(SubjectManagementError):
        SubjectManager(data).remove(name)
    assert (data / "AIL303m").is_dir()


def test_subject_remove_rejects_symlink_inside_or_as_destination(tmp_path: Path) -> None:
    data = tmp_path / "DATA"
    outside = tmp_path / "outside"
    outside.mkdir()
    data.mkdir()
    (data / "LINK101").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SubjectManagementError):
        SubjectManager(data).remove("LINK101")
    subject = data / "AIL303m"
    subject.mkdir()
    (subject / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SubjectManagementError):
        SubjectManager(data).remove("AIL303m")
    assert outside.is_dir() and subject.is_dir()


def test_subject_remove_rejects_unsafe_recovery_dir(tmp_path: Path) -> None:
    data = tmp_path / "DATA"
    subject = data / "AIL303m"
    subject.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".src-learning-recovery").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SubjectManagementError, match="Vùng khôi phục"):
        SubjectManager(data).remove("AIL303m")
    assert subject.is_dir() and not list(outside.iterdir())


def test_restore_requires_backup_inside_recovery(tmp_path: Path) -> None:
    data = tmp_path / "DATA"
    data.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(SubjectManagementError, match="Bản khôi phục"):
        SubjectManager(data).restore("AIL303m", outside)


def test_duplicate_requires_consent_and_replacement_keeps_backup(tmp_path: Path) -> None:
    archive = make_subject_archive(tmp_path)
    installer = installer_for(archive)
    data = tmp_path / "app" / "DATA"
    old = data / "AIL303m"
    old.mkdir(parents=True)
    (old / "old.txt").write_text("original", encoding="utf-8")
    with pytest.raises(Exception, match="đã tồn tại"):
        installer.install("approved-drive-file-id", data)
    assert (old / "old.txt").is_file()
    result = installer.install("approved-drive-file-id", data, replace_existing=True)
    assert result.backup_path is not None
    assert (result.backup_path / "old.txt").read_text(encoding="utf-8") == "original"
    assert (old / "answers.csv").is_file()


def test_replace_rolls_back_if_new_install_fails(tmp_path: Path, monkeypatch) -> None:
    archive = make_subject_archive(tmp_path)
    installer = installer_for(archive)
    data = tmp_path / "app" / "DATA"
    old = data / "AIL303m"
    old.mkdir(parents=True)
    (old / "old.txt").write_text("original", encoding="utf-8")
    original_replace = os.replace

    def fail_new(source, target):
        if Path(target) == old and Path(source).name == "AIL303m":
            raise OSError("disk error")
        return original_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_new)
    with pytest.raises(DataPackageError, match="Không thể cài đặt"):
        installer.install("approved-drive-file-id", data, replace_existing=True)
    assert (old / "old.txt").read_text(encoding="utf-8") == "original"
    assert not (old / "answers.csv").exists()


def test_scanner_does_not_follow_subject_or_image_symlinks(tmp_path: Path) -> None:
    data = tmp_path / "DATA"
    outside = tmp_path / "outside"
    outside.mkdir()
    Image.new("RGB", (10, 10), "white").save(outside / "question.png")
    data.mkdir()
    (data / "LINK101").symlink_to(outside, target_is_directory=True)
    category = data / "SAFE101" / "Selections_1_choose"
    category.mkdir(parents=True)
    (category / "external.png").symlink_to(outside / "question.png")
    subjects = DataScannerService(data).scan()
    assert subjects == []
