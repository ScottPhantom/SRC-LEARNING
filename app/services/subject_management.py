"""Safe, reversible filesystem operations for installed subjects."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import CATEGORIES, IMAGE_EXTENSIONS


class SubjectManagementError(RuntimeError):
    """A filesystem or validation failure that may be shown to the user."""


@dataclass(frozen=True, slots=True)
class SubjectInfo:
    name: str
    path: Path
    question_count: int
    size_bytes: int
    status: str


def subject_destination(data_dir: Path, name: str) -> Path:
    """Return only an immediate DATA child; never accept an arbitrary path."""
    if (
        not name
        or name in {".", ".."}
        or Path(name).name != name
        or "/" in name
        or "\\" in name
        or name.startswith(".")
        or "\x00" in name
    ):
        raise SubjectManagementError("Tên môn học không phải tên thư mục hợp lệ.")
    root = Path(data_dir).expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise SubjectManagementError("Thư mục DATA không hợp lệ.")
    destination = root / name
    if destination.parent != root or destination.is_symlink():
        raise SubjectManagementError("Đường dẫn môn học không an toàn.")
    return destination


def inspect_tree(path: Path) -> tuple[int, int, bool]:
    """Count images/bytes without following symlinks outside the subject."""
    question_count = size = 0
    unsafe = False
    for current, directories, files in os.walk(path, followlinks=False):
        for name in directories[:]:
            child = Path(current) / name
            if child.is_symlink():
                unsafe = True
                directories.remove(name)
        for name in files:
            child = Path(current) / name
            if child.is_symlink():
                unsafe = True
                continue
            size += child.stat().st_size
            if (
                child.suffix.lower() in IMAGE_EXTENSIONS
                and child.parent.parent == path
                and child.parent.name in CATEGORIES
            ):
                question_count += 1
    return question_count, size, unsafe


class SubjectManager:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).expanduser().resolve()

    def inventory(self) -> list[SubjectInfo]:
        if not self.data_dir.is_dir():
            return []
        result = []
        for path in sorted(
            self.data_dir.iterdir(), key=lambda item: item.name.casefold()
        ):
            if path.name.startswith("."):
                continue
            if path.is_symlink():
                result.append(
                    SubjectInfo(path.name, path, 0, 0, "Đường dẫn không an toàn")
                )
                continue
            if not path.is_dir():
                continue
            count, size, unsafe = inspect_tree(path)
            status = (
                "Đường dẫn không an toàn"
                if unsafe
                else "Sẵn sàng"
                if count and (path / "answers.csv").is_file()
                else "Thiếu dữ liệu"
            )
            result.append(SubjectInfo(path.name, path, count, size, status))
        return result

    def destination(self, name: str, *, require_existing: bool = True) -> Path:
        try:
            destination = subject_destination(self.data_dir, name)
            if require_existing and not destination.is_dir():
                raise SubjectManagementError(f"Không tìm thấy môn {name} trong DATA.")
            if destination.exists() and inspect_tree(destination)[2]:
                raise SubjectManagementError(
                    "Môn học chứa liên kết ngoài DATA; không thể thao tác an toàn."
                )
            return destination
        except OSError as exc:
            raise SubjectManagementError(f"Không kiểm tra được môn học: {exc}") from exc

    def _recovery_dir(self) -> Path:
        recovery = self.data_dir.parent / ".src-learning-recovery"
        try:
            if recovery.is_symlink():
                raise SubjectManagementError("Vùng khôi phục là liên kết không an toàn.")
            recovery.mkdir(mode=0o700, exist_ok=True)
            if not recovery.is_dir() or recovery.resolve() != recovery:
                raise SubjectManagementError("Vùng khôi phục không hợp lệ.")
        except OSError as exc:
            raise SubjectManagementError(f"Không tạo được vùng khôi phục: {exc}") from exc
        return recovery

    def reserve_recovery_path(self, name: str) -> Path:
        self.destination(name, require_existing=False)
        return self._recovery_dir() / f"{name}-{uuid.uuid4().hex}"

    def remove(self, name: str) -> Path:
        destination = self.destination(name)
        backup = self.reserve_recovery_path(name)
        try:
            os.replace(destination, backup)
        except OSError as exc:
            raise SubjectManagementError(
                f"Không chuyển được môn vào vùng khôi phục: {exc}"
            ) from exc
        return backup

    def restore(self, name: str, backup: Path) -> Path | None:
        """Restore a recovery child, retaining a displaced new version."""
        destination = self.destination(name, require_existing=False)
        recovery = self._recovery_dir()
        backup = Path(backup)
        if backup.parent != recovery or backup.is_symlink() or not backup.is_dir():
            raise SubjectManagementError("Bản khôi phục không nằm trong vùng an toàn.")
        displaced = self.reserve_recovery_path(name) if destination.exists() else None
        try:
            if displaced is not None:
                os.replace(destination, displaced)
            os.replace(backup, destination)
        except OSError as exc:
            if displaced is not None and displaced.exists() and not destination.exists():
                try:
                    os.replace(displaced, destination)
                except OSError:
                    pass
            raise SubjectManagementError(
                f"Không khôi phục được môn học; bản cũ ở {backup}: {exc}"
            ) from exc
        return displaced
