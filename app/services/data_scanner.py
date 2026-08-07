from __future__ import annotations

import hashlib
import unicodedata
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.config import CATEGORIES, IMAGE_EXTENSIONS
from app.domain.models import Question, Subject


class DataScannerService:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).expanduser().resolve()

    def scan(self) -> list[Subject]:
        if not self.data_dir.exists() or not self.data_dir.is_dir():
            return []
        subjects: list[Subject] = []
        for subject_dir in sorted(
            (p for p in self.data_dir.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name.casefold(),
        ):
            subjects.append(self._scan_subject(subject_dir))
        return subjects

    def _scan_subject(self, subject_dir: Path) -> Subject:
        subject = Subject(name=subject_dir.name, path=subject_dir)
        for category in CATEGORIES:
            category_dir = subject_dir / category
            if not category_dir.is_dir():
                continue
            candidates = sorted(
                (
                    path
                    for path in category_dir.iterdir()
                    if path.is_file()
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
                    )
                )
        return subject
