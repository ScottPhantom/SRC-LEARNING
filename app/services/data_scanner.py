from __future__ import annotations

import csv
import hashlib
import unicodedata
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.config import CATEGORIES, IMAGE_EXTENSIONS
from app.domain.models import Question, Subject, parse_option_letters
from app.services.subject_management import inspect_tree


class DataScannerService:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).expanduser().resolve()

    def scan(self) -> list[Subject]:
        if not self.data_dir.exists() or not self.data_dir.is_dir():
            return []
        subjects: list[Subject] = []
        for subject_dir in sorted(
            (p for p in self.data_dir.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")),
            key=lambda p: p.name.casefold(),
        ):
            if inspect_tree(subject_dir)[2]:
                continue
            subjects.append(self._scan_subject(subject_dir))
        return subjects

    def _scan_subject(self, subject_dir: Path) -> Subject:
        subject = Subject(name=subject_dir.name, path=subject_dir)
        option_letters = self._read_option_letters(subject_dir)
        for category in CATEGORIES:
            category_dir = subject_dir / category
            if category_dir.is_symlink() or not category_dir.is_dir():
                continue
            candidates = sorted(
                (
                    path
                    for path in category_dir.iterdir()
                    if path.is_file()
                    and not path.is_symlink()
                    and not path.name.startswith(".")
                    and path.suffix.lower() in IMAGE_EXTENSIONS
                ),
                key=lambda p: p.name.casefold(),
            )
            for image_path in candidates:
                try:
                    with Image.open(image_path) as image:
                        image.verify()
                except (OSError, UnidentifiedImageError, ValueError):
                    subject.invalid_images.append(str(image_path))
                    continue
                relative = unicodedata.normalize(
                    "NFC", image_path.relative_to(subject_dir).as_posix()
                )
                stable_key = f"{unicodedata.normalize('NFC', subject.name)}/{relative}"
                question_id = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()
                subject.questions.append(
                    Question(
                        id=question_id,
                        subject=subject.name,
                        category=category,
                        relative_path=relative,
                        absolute_path=image_path,
                        option_letters=option_letters.get(relative, ()),
                    )
                )
        return subject

    @staticmethod
    def _read_option_letters(subject_dir: Path) -> dict[str, tuple[str, ...]]:
        """Read optional per-image choices; old banks retain their A-D default."""
        metadata = subject_dir / "question_metadata.csv"
        if not metadata.is_file() or metadata.is_symlink():
            return {}
        result: dict[str, tuple[str, ...]] = {}
        with metadata.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not {"image_name", "option_letters"}.issubset(reader.fieldnames or []):
                return {}
            for row in reader:
                relative = unicodedata.normalize("NFC", (row["image_name"] or "").strip())
                letters = parse_option_letters(row["option_letters"])
                if letters:
                    result[relative] = letters
        return result
