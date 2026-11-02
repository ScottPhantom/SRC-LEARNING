from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath

import gdown
from tqdm import tqdm

from app.config import CATEGORIES, IMAGE_EXTENSIONS
from app.repositories.answer_key import AnswerKeyRepository
from app.services.data_scanner import DataScannerService

ProgressCallback = Callable[[str, int, str], None]
DownloadFunction = Callable[[str, Path, int, ProgressCallback], Path]

MAX_ARCHIVE_ENTRIES = 100_000
MAX_UNCOMPRESSED_BYTES = 5 * 1024 * 1024 * 1024
DRIVE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}$")
DRIVE_URL_PATTERNS = (
    re.compile(r"/d/([A-Za-z0-9_-]+)"),
    re.compile(r"[?&]id=([A-Za-z0-9_-]+)"),
)


class DataPackageError(RuntimeError):
    """Base error safe to show in the data-package UI."""


class UnknownPackageCodeError(DataPackageError):
    pass


class ExistingSubjectError(DataPackageError):
    pass


@dataclass(frozen=True, slots=True)
class DataPackageSpec:
    subject: str
    file_id: str
    sha256: str
    archive_size: int
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class DataInstallResult:
    subject: str
    destination: Path
    question_count: int
    archive_sha256: str


class DataPackageCatalog:
    def __init__(self, packages: list[DataPackageSpec]):
        self._by_file_id = {package.file_id: package for package in packages}

    @classmethod
    def bundled(cls) -> "DataPackageCatalog":
        manifest = resources.files("app.resources").joinpath("data_manifest.json")
        with manifest.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("schema_version") != 1:
            raise DataPackageError("Phiên bản data manifest không được hỗ trợ.")
        packages = [
            DataPackageSpec(
                subject=str(item["subject"]),
                file_id=str(item["file_id"]),
                sha256=str(item["sha256"]).lower(),
                archive_size=int(item["archive_size"]),
                enabled=bool(item.get("enabled", False)),
            )
            for item in payload.get("packages", [])
        ]
        return cls(packages)

    @staticmethod
    def extract_file_id(code: str) -> str:
        value = code.strip()
        if DRIVE_ID_PATTERN.fullmatch(value):
            return value
        for pattern in DRIVE_URL_PATTERNS:
            match = pattern.search(value)
            if match:
                return match.group(1)
        raise UnknownPackageCodeError(
            "Mã tải không đúng định dạng Google Drive File ID hoặc link chia sẻ."
        )

    def resolve(self, code: str) -> DataPackageSpec:
        file_id = self.extract_file_id(code)
        package = self._by_file_id.get(file_id)
        if package is None or not package.enabled:
            raise UnknownPackageCodeError(
                "Mã này chưa nằm trong danh sách môn học được SRC-LEARNING phê duyệt."
            )
        return package


class DataPackageInstaller:
    def __init__(
        self,
        catalog: DataPackageCatalog | None = None,
        download_file: DownloadFunction | None = None,
    ):
        self.catalog = catalog or DataPackageCatalog.bundled()
        self.download_file = download_file or self._download_with_gdown

    def install(
        self,
        code: str,
        data_dir: Path,
        *,
        replace_existing: bool = False,
        progress: ProgressCallback | None = None,
    ) -> DataInstallResult:
        report = progress or (lambda _stage, _percent, _message: None)
        package = self.catalog.resolve(code)
        data_dir = Path(data_dir).expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        destination = data_dir / package.subject
        if (destination.exists() or destination.is_symlink()) and not replace_existing:
            raise ExistingSubjectError(
                f"Môn {package.subject} đã tồn tại. Hãy xác nhận trước khi thay thế."
            )

        with tempfile.TemporaryDirectory(
            prefix=".src-learning-import-", dir=data_dir.parent
        ) as temp_name:
            temp_root = Path(temp_name)
            archive_path = temp_root / f"{package.subject}.zip"
            report("download", 0, f"Đang tải {package.subject} từ Google Drive…")
            downloaded = self.download_file(
                package.file_id, archive_path, package.archive_size, report
            )
            if not downloaded.is_file():
                raise DataPackageError("Google Drive không trả về tệp dữ liệu hợp lệ.")

            digest = self._sha256(downloaded, report)
            if digest != package.sha256:
                raise DataPackageError(
                    "SHA-256 không khớp. Tệp tải xuống có thể bị lỗi hoặc không đúng phiên bản."
                )

            extract_root = temp_root / "extracted"
            self._safe_extract(downloaded, extract_root, report)
            source, question_count = self._validate_subject(
                extract_root, package.subject, report
            )
            self._atomic_install(source, destination, replace_existing)
            report("complete", 100, f"Đã cài đặt {package.subject} thành công.")
            return DataInstallResult(
                subject=package.subject,
                destination=destination,
                question_count=question_count,
                archive_sha256=digest,
            )

    @staticmethod
    def _download_with_gdown(
        file_id: str,
        output: Path,
        expected_size: int,
        progress: ProgressCallback,
    ) -> Path:
        stop_monitor = threading.Event()

        def monitor() -> None:
            current = 0
            with tqdm(
                total=expected_size,
                desc="Tải dữ liệu",
                unit="B",
                unit_scale=True,
                disable=True,
            ) as bar:
                while not stop_monitor.wait(0.1):
                    candidates = [output, *output.parent.glob(f"{output.name}*.part")]
                    observed = max(
                        (path.stat().st_size for path in candidates if path.is_file()),
                        default=0,
                    )
                    delta = max(0, observed - current)
                    if delta:
                        bar.update(delta)
                        current = observed
                    percent = min(99, int(observed * 100 / max(1, expected_size)))
                    progress("download", percent, "Đang tải dữ liệu từ Google Drive…")

        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        try:
            result = gdown.download(
                id=file_id,
                output=str(output),
                quiet=True,
                use_cookies=False,
                resume=False,
            )
        except Exception as exc:
            raise DataPackageError(
                "Không tải được dữ liệu. Hãy kiểm tra kết nối và quyền chia sẻ Google Drive."
            ) from exc
        finally:
            stop_monitor.set()
            monitor_thread.join(timeout=1.0)
        if not result:
            raise DataPackageError(
                "Không tải được dữ liệu. Mã có thể sai hoặc tệp chưa được chia sẻ."
            )
        progress("download", 100, "Đã tải xong. Đang kiểm tra tệp…")
        return Path(result)

    @staticmethod
    def _sha256(path: Path, progress: ProgressCallback) -> str:
        digest = hashlib.sha256()
        total = path.stat().st_size
        processed = 0
        with path.open("rb") as handle, tqdm(
            total=total,
            desc="Kiểm tra SHA-256",
            unit="B",
            unit_scale=True,
            disable=True,
        ) as bar:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                processed += len(chunk)
                bar.update(len(chunk))
                progress(
                    "verify",
                    min(100, int(processed * 100 / max(1, total))),
                    "Đang kiểm tra tính toàn vẹn của tệp…",
                )
        return digest.hexdigest()

    @classmethod
    def _safe_extract(
        cls, archive_path: Path, extract_root: Path, progress: ProgressCallback
    ) -> None:
        try:
            archive = zipfile.ZipFile(archive_path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise DataPackageError("Tệp tải xuống không phải ZIP hợp lệ.") from exc

        with archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_ENTRIES:
                raise DataPackageError("ZIP chứa quá nhiều mục và đã bị từ chối.")
            total = sum(member.file_size for member in members)
            if total > MAX_UNCOMPRESSED_BYTES:
                raise DataPackageError("ZIP vượt quá giới hạn giải nén an toàn.")
            extract_root.mkdir(parents=True, exist_ok=True)
            processed = 0
            with tqdm(
                total=total,
                desc="Giải nén dữ liệu",
                unit="B",
                unit_scale=True,
                disable=True,
            ) as bar:
                for member in members:
                    relative = cls._safe_member_path(member)
                    target = extract_root.joinpath(*relative.parts)
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open("wb") as output:
                        while chunk := source.read(1024 * 1024):
                            output.write(chunk)
                            processed += len(chunk)
                            bar.update(len(chunk))
                            progress(
                                "extract",
                                min(100, int(processed * 100 / max(1, total))),
                                f"Đang giải nén {member.filename}…",
                            )

    @staticmethod
    def _safe_member_path(member: zipfile.ZipInfo) -> PurePosixPath:
        raw = member.filename.replace("\\", "/")
        relative = PurePosixPath(raw)
        mode = member.external_attr >> 16
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
            or (relative.parts and ":" in relative.parts[0])
            or stat.S_ISLNK(mode)
        ):
            raise DataPackageError(
                f"ZIP chứa đường dẫn không an toàn: {member.filename}"
            )
        return relative

    @staticmethod
    def _validate_subject(
        extract_root: Path, expected_subject: str, progress: ProgressCallback
    ) -> tuple[Path, int]:
        candidates = (
            extract_root / "DATA" / expected_subject,
            extract_root / expected_subject,
        )
        subject_path = next((path for path in candidates if path.is_dir()), None)
        if subject_path is None:
            raise DataPackageError(
                f"ZIP phải chứa DATA/{expected_subject} hoặc {expected_subject}."
            )
        if not (subject_path / "answers.csv").is_file():
            raise DataPackageError("Gói môn học thiếu answers.csv.")
        if not any((subject_path / category).is_dir() for category in CATEGORIES):
            raise DataPackageError("Gói môn học không có thư mục loại câu hỏi hợp lệ.")
        if not any(
            path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
            for category in CATEGORIES
            for path in (subject_path / category).glob("*")
            if (subject_path / category).is_dir()
        ):
            raise DataPackageError("Gói môn học không chứa ảnh câu hỏi hợp lệ.")

        progress("validate", 15, "Đang quét và kiểm tra dữ liệu môn học…")
        subjects = DataScannerService(subject_path.parent).scan()
        subject = next((item for item in subjects if item.name == expected_subject), None)
        if subject is None or not subject.questions:
            raise DataPackageError("Không quét được câu hỏi từ gói môn học.")
        if subject.invalid_images:
            raise DataPackageError(
                f"Gói môn học có {len(subject.invalid_images)} ảnh bị lỗi."
            )
        progress("validate", 65, "Đang kiểm tra answers.csv…")
        answer_report = AnswerKeyRepository().load(subject.path, subject.questions)
        if (
            not answer_report.file_found
            or answer_report.missing
            or answer_report.invalid
            or answer_report.duplicates
            or answer_report.unknown_paths
        ):
            raise DataPackageError(
                "answers.csv không ánh xạ đầy đủ và hợp lệ với toàn bộ câu hỏi."
            )
        progress("validate", 100, f"Đã xác minh {subject.question_count} câu hỏi.")
        return subject.path, subject.question_count

    @staticmethod
    def _atomic_install(
        source: Path, destination: Path, replace_existing: bool
    ) -> None:
        backup = destination.with_name(
            f".{destination.name}.backup-{os.getpid()}-{time.time_ns()}"
        )
        had_existing = destination.exists() or destination.is_symlink()
        if had_existing and not replace_existing:
            raise ExistingSubjectError(
                f"Môn {destination.name} đã tồn tại. Hãy xác nhận trước khi thay thế."
            )
        try:
            if had_existing:
                os.replace(destination, backup)
            os.replace(source, destination)
        except Exception:
            if had_existing and backup.exists() and not destination.exists():
                os.replace(backup, destination)
            raise
        else:
            if backup.is_symlink() or backup.is_file():
                backup.unlink(missing_ok=True)
            elif backup.is_dir():
                shutil.rmtree(backup)


def package_from_mapping(item: Mapping[str, object]) -> DataPackageSpec:
    """Small public helper used by focused tests and future catalog providers."""
    return DataPackageSpec(
        subject=str(item["subject"]),
        file_id=str(item["file_id"]),
        sha256=str(item["sha256"]),
        archive_size=int(item["archive_size"]),
        enabled=bool(item.get("enabled", True)),
    )
