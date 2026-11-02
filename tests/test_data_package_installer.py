from __future__ import annotations

import csv
import hashlib
import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.services.data_package_installer import (
    DataPackageCatalog,
    DataPackageError,
    DataPackageInstaller,
    DataPackageSpec,
    UnknownPackageCodeError,
)


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
