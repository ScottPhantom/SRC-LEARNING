from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import shutil
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from app.config import CATEGORIES, MULTIPLE_CATEGORY
from app.domain.models import Question, Subject, normalize_answer
from app.repositories.answer_key import AnswerKeyRepository, normalize_relative_path
from app.repositories.database import Database

LOGGER = logging.getLogger(__name__)
MANIFEST_SCHEMA_VERSION = 1
VERSION_DIRECTORY = "answer_versions"
ACTIVE_MANIFEST = "manifest.json"
PENDING_ANSWERS_FILE = "answers.pending.csv"

NOTIFICATION_CATEGORY_LABELS = {
    "Selections_1_choose": "Single Choice",
    "Selections_Multiple_choose": "Multiple Choice",
    "True_False": "True/False",
    "Fill_blanks": "Fill Blanks",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_question_id(subject: str, relative_path: str) -> str:
    stable_key = (
        f"{unicodedata.normalize('NFC', subject)}/"
        f"{normalize_relative_path(relative_path)}"
    )
    return hashlib.sha256(stable_key.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class BankEntry:
    logical_id: str
    revision: int
    question_id: str
    bank_version: int
    relative_path: str
    category: str
    answer: str
    file_sha256: str = ""
    active: bool = True
    supersedes_question_id: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> BankEntry:
        return cls(
            logical_id=str(value["logical_id"]),
            revision=int(value.get("revision", 1)),
            question_id=str(value["question_id"]),
            bank_version=int(value.get("bank_version", 1)),
            relative_path=normalize_relative_path(str(value["relative_path"])),
            category=str(value["category"]),
            answer=normalize_answer(str(value.get("answer", ""))),
            file_sha256=str(value.get("file_sha256", "")),
            active=bool(value.get("active", True)),
            supersedes_question_id=(
                str(value["supersedes_question_id"])
                if value.get("supersedes_question_id")
                else None
            ),
        )


@dataclass(slots=True)
class BankChange:
    kind: str
    old: BankEntry | None = None
    question: Question | None = None
    new_answer: str = ""
    reason: str = ""


@dataclass(slots=True)
class BankUpdateResult:
    subject: str
    previous_version: int = 0
    bank_version: int = 0
    question_count: int = 0
    changes: list[BankChange] = field(default_factory=list)
    applied: bool = False
    initialized: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def added(self) -> list[BankChange]:
        return [change for change in self.changes if change.kind == "ADD"]

    @property
    def updated(self) -> list[BankChange]:
        return [change for change in self.changes if change.kind == "UPDATE"]

    @property
    def deleted(self) -> list[BankChange]:
        return [change for change in self.changes if change.kind == "DELETE"]

    @property
    def notification(self) -> str:
        messages: list[str] = []
        if self.added:
            counts: dict[str, int] = {}
            for change in self.added:
                if change.question is not None:
                    counts[change.question.category] = (
                        counts.get(change.question.category, 0) + 1
                    )
            detail = ", ".join(
                f"{amount} câu {NOTIFICATION_CATEGORY_LABELS.get(category, category)}"
                for category, amount in sorted(counts.items())
            )
            messages.append(f"Đã bổ sung {detail}.")
        for change in self.updated:
            if change.old is None or change.question is None:
                continue
            old_category = NOTIFICATION_CATEGORY_LABELS.get(
                change.old.category, change.old.category
            )
            new_category = NOTIFICATION_CATEGORY_LABELS.get(
                change.question.category, change.question.category
            )
            name = PurePosixPath(change.question.relative_path).stem
            messages.append(
                f"{name} đã được cập nhật từ {old_category} — đáp án "
                f"{change.old.answer or 'trống'} sang {new_category} — đáp án "
                f"{change.new_answer}."
            )
        if self.deleted:
            messages.append(
                f"Đã cập nhật bộ {self.question_count} câu ôn tập mới nhất."
            )
        return "\n".join(messages)


AnswerResolver = Callable[[Question], str]


class QuestionBankUpdateChecker:
    """Đối chiếu DATA với answer bank active và áp dụng một version nguyên tử."""

    def __init__(
        self,
        database: Database,
        crop_region: tuple[float, float, float, float],
        answer_resolver: AnswerResolver | None = None,
    ):
        self.database = database
        self.crop_region = crop_region
        self.answer_resolver = answer_resolver or self._ocr_answer

    def _ocr_answer(self, question: Question) -> str:
        # OCR is an optional, heavy feature. Import it only when a newly added
        # question has no approved answer in answers.csv.
        from app.services.answer_ocr import crop_answer, read_image_unicode, recognize

        image = read_image_unicode(question.absolute_path)
        crop = crop_answer(image, self.crop_region)
        return recognize(crop, question.category == MULTIPLE_CATEGORY, question.options)

    @staticmethod
    def _notification_change_rows(
        changes: list[BankChange],
    ) -> list[dict[str, str | None]]:
        """Serialize UI notification data without changing detection semantics."""
        rows: list[dict[str, str | None]] = []
        for change in changes:
            old = change.old
            question = change.question
            rows.append(
                {
                    "change_type": change.kind,
                    "logical_id": (
                        old.logical_id
                        if old is not None
                        else question.id
                        if question is not None
                        else ""
                    ),
                    "question_id": (
                        question.id
                        if question is not None
                        else old.question_id
                        if old is not None
                        else None
                    ),
                    "old_path": old.relative_path if old is not None else None,
                    "new_path": (
                        normalize_relative_path(question.relative_path)
                        if question is not None
                        else None
                    ),
                    "old_category": old.category if old is not None else None,
                    "new_category": question.category if question is not None else None,
                    "old_answer": old.answer if old is not None else None,
                    "new_answer": change.new_answer if question is not None else None,
                    "reason": change.reason,
                }
            )
        return rows

    @staticmethod
    def _read_answers(path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        answers: dict[str, str] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = [
                (header or "").strip().casefold() for header in reader.fieldnames or []
            ]
            if headers != ["image_name", "correct_answer"]:
                raise ValueError(
                    f"{path} phải có đúng hai cột image_name,correct_answer"
                )
            for row in reader:
                values = list(row.values())
                relative = (
                    normalize_relative_path(str(values[0] or "")) if values else ""
                )
                if relative:
                    answers[relative] = normalize_answer(
                        str(values[1] or "") if len(values) > 1 else ""
                    )
        return answers

    @staticmethod
    def _load_manifest(path: Path) -> tuple[int, list[BankEntry]]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"Manifest phải là một JSON object: {path}")
        try:
            if int(value.get("schema_version", 0)) != MANIFEST_SCHEMA_VERSION:
                raise ValueError(f"Manifest không được hỗ trợ: {path}")
            version = int(value["bank_version"])
            rows = value["questions"]
            if version < 1 or not isinstance(rows, list):
                raise ValueError("Version hoặc danh sách revision không hợp lệ")
            return version, [BankEntry.from_dict(item) for item in rows]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Manifest thiếu trường hoặc sai định dạng: {path}") from exc

    def restore_missing_baseline(self, subject: Subject) -> bool:
        """Reconcile a legacy imported manifest without modifying study state."""
        active = subject.path / VERSION_DIRECTORY / ACTIVE_MANIFEST
        if subject.path.is_symlink() or active.parent.is_symlink() or active.is_symlink():
            raise ValueError("Không phục hồi từ đường dẫn answer version là symlink.")
        if not active.exists():
            return False
        version, entries = self._load_manifest(active)
        payload = json.loads(active.read_text(encoding="utf-8"))
        if version < 1 or payload.get("subject") != subject.name:
            raise ValueError("Manifest answer version không khớp môn đang học.")
        recorded = self.database.recorded_bank_version(subject.name)
        if recorded is not None:
            if recorded != version:
                raise ValueError(
                    f"SQLite v{recorded} khác manifest v{version}; không tự ghi đè lịch sử học."
                )
            return False
        snapshot_manifest = active.parent / f"manifest.v{version}.json"
        snapshot_answers = active.parent / f"answers.v{version}.csv"
        if any(
            path.is_symlink() or not path.is_file()
            for path in (active, snapshot_manifest, snapshot_answers)
        ):
            raise ValueError("Thiếu snapshot answer version an toàn để phục hồi SQLite.")
        if snapshot_manifest.read_bytes() != active.read_bytes():
            raise ValueError("Snapshot manifest không nhất quán; không phục hồi SQLite.")
        paths: set[str] = set()
        logical_ids: set[str] = set()
        expected_answers: dict[str, str] = {}
        for entry in entries:
            path = PurePosixPath(entry.relative_path)
            if (
                not entry.active or path.is_absolute() or ".." in path.parts
                or len(path.parts) != 2 or path.parts[0] not in CATEGORIES
                or entry.category != path.parts[0]
                or entry.question_id != stable_question_id(subject.name, entry.relative_path)
                or entry.revision < 1 or not 1 <= entry.bank_version <= version
                or entry.relative_path in paths or entry.logical_id in logical_ids
            ):
                raise ValueError("Snapshot chứa revision hoặc danh tính câu hỏi không hợp lệ.")
            paths.add(entry.relative_path)
            logical_ids.add(entry.logical_id)
            expected_answers[entry.relative_path] = entry.answer
        if self._read_answers(snapshot_answers) != expected_answers:
            raise ValueError("Snapshot đáp án không khớp manifest; không phục hồi SQLite.")
        return self.database.restore_missing_question_bank_baseline(
            subject=subject.name,
            bank_version=version,
            revisions=[asdict(entry) for entry in entries],
        )

    @staticmethod
    def _manifest_text(
        subject: str,
        version: int,
        entries: list[BankEntry],
        summary: dict[str, int],
    ) -> str:
        payload = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "subject": subject,
            "bank_version": version,
            "generated_at": utc_now(),
            "summary": summary,
            "questions": [asdict(entry) for entry in entries],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    @staticmethod
    def _answers_bytes(entries: list[BankEntry]) -> bytes:
        from io import StringIO

        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["image_name", "correct_answer"])
        for entry in sorted(entries, key=lambda item: item.relative_path.casefold()):
            if entry.active:
                writer.writerow([entry.relative_path, entry.answer])
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    @classmethod
    def _atomic_write_batch(cls, files: dict[Path, bytes]) -> None:
        """Restore every destination if publishing any file in the batch fails."""

        originals = {
            path: path.read_bytes() if path.exists() else None for path in files
        }
        try:
            for path, data in files.items():
                cls._atomic_write(path, data)
        except OSError:
            for path, original in originals.items():
                try:
                    if original is None:
                        path.unlink(missing_ok=True)
                    else:
                        cls._atomic_write(path, original)
                except OSError:
                    LOGGER.exception("Không thể rollback file answer bank: %s", path)
            raise

    @staticmethod
    def _change_report_bytes(changes: list[BankChange]) -> bytes:
        from io import StringIO

        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "change",
                "old_path",
                "new_path",
                "old_category",
                "new_category",
                "old_answer",
                "new_answer",
                "reason",
            ]
        )
        for change in changes:
            writer.writerow(
                [
                    change.kind,
                    change.old.relative_path if change.old else "",
                    change.question.relative_path if change.question else "",
                    change.old.category if change.old else "",
                    change.question.category if change.question else "",
                    change.old.answer if change.old else "",
                    change.new_answer,
                    change.reason,
                ]
            )
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    def _bootstrap_entries(
        self, subject: Subject, raw_answers: dict[str, str]
    ) -> list[BankEntry]:
        current = {
            normalize_relative_path(question.relative_path): question
            for question in subject.questions
        }
        entries: list[BankEntry] = []
        for relative, answer in raw_answers.items():
            question = current.get(relative)
            category = (
                question.category
                if question is not None
                else (PurePosixPath(relative).parts[0] if "/" in relative else "")
            )
            question_id = (
                question.id
                if question is not None
                else stable_question_id(subject.name, relative)
            )
            entries.append(
                BankEntry(
                    logical_id=question_id,
                    revision=1,
                    question_id=question_id,
                    bank_version=1,
                    relative_path=relative,
                    category=category,
                    answer=answer,
                    file_sha256=(
                        file_sha256(question.absolute_path)
                        if question is not None
                        else ""
                    ),
                )
            )
        return entries

    @staticmethod
    def _pair_moves(
        removed: list[BankEntry], added: list[Question], hashes: dict[str, str]
    ) -> tuple[list[tuple[BankEntry, Question, str]], list[BankEntry], list[Question]]:
        pairs: list[tuple[BankEntry, Question, str]] = []
        unmatched_old = list(removed)
        unmatched_new = list(added)

        for old in list(unmatched_old):
            if not old.file_sha256:
                continue
            matches = [
                question
                for question in unmatched_new
                if hashes[normalize_relative_path(question.relative_path)]
                == old.file_sha256
            ]
            if len(matches) == 1:
                question = matches[0]
                pairs.append((old, question, "same-file-sha256"))
                unmatched_old.remove(old)
                unmatched_new.remove(question)

        for old in list(unmatched_old):
            basename = PurePosixPath(old.relative_path).name.casefold()
            matches = [
                question
                for question in unmatched_new
                if PurePosixPath(question.relative_path).name.casefold() == basename
            ]
            if len(matches) == 1:
                question = matches[0]
                pairs.append((old, question, "unique-basename"))
                unmatched_old.remove(old)
                unmatched_new.remove(question)
        return pairs, unmatched_old, unmatched_new

    def check_subject(
        self, subject: Subject, *, apply: bool = True
    ) -> BankUpdateResult:
        answers_path = subject.path / AnswerKeyRepository.FILE_NAME
        pending_answers_path = subject.path / PENDING_ANSWERS_FILE
        versions_dir = subject.path / VERSION_DIRECTORY
        active_manifest_path = versions_dir / ACTIVE_MANIFEST
        result = BankUpdateResult(
            subject=subject.name, question_count=len(subject.questions)
        )

        # The updater manages successful answer banks; initial full OCR remains the
        # explicit responsibility of build_answers.py.
        if not answers_path.exists():
            return result

        try:
            raw_answers = self._read_answers(answers_path)
            pending_answers = self._read_answers(pending_answers_path)
            supplied_answers = {**raw_answers, **pending_answers}
            if active_manifest_path.exists():
                previous_version, old_entries = self._load_manifest(
                    active_manifest_path
                )
                if apply:
                    self.restore_missing_baseline(subject)
            else:
                baseline = self.database.question_bank_baseline(subject.name)
                if baseline is None:
                    previous_version = 1
                    old_entries = self._bootstrap_entries(subject, raw_answers)
                else:
                    previous_version, stored_entries = baseline
                    old_entries = [BankEntry.from_dict(entry) for entry in stored_entries]
                    if not old_entries and subject.questions:
                        raise ValueError("SQLite có version nhưng thiếu revision; không khởi tạo lại lịch sử.")
                result.initialized = True
        except (
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
            csv.Error,
        ) as exc:
            result.errors.append(str(exc))
            return result

        result.previous_version = previous_version
        current = {
            normalize_relative_path(question.relative_path): question
            for question in subject.questions
        }
        hashes: dict[str, str] = {}
        try:
            hashes = {
                relative: file_sha256(question.absolute_path)
                for relative, question in current.items()
            }
        except OSError as exc:
            result.errors.append(str(exc))
            return result

        old_active = {
            entry.relative_path: entry for entry in old_entries if entry.active
        }
        exact_paths = set(old_active) & set(current)
        removed = [old_active[path] for path in sorted(set(old_active) - set(current))]
        added = [current[path] for path in sorted(set(current) - set(old_active))]
        move_pairs, removed, added = self._pair_moves(removed, added, hashes)

        changes: list[BankChange] = []
        for old, question, reason in move_pairs:
            changes.append(BankChange("UPDATE", old, question, reason=reason))
        for old in removed:
            changes.append(BankChange("DELETE", old=old, reason="missing-from-data"))
        for question in added:
            changes.append(BankChange("ADD", question=question, reason="new-path"))

        for relative in sorted(exact_paths):
            old = old_active[relative]
            question = current[relative]
            supplied_answer = supplied_answers.get(relative, old.answer)
            answer_changed = (
                supplied_answer != old.answer
                and AnswerKeyRepository.validate(question, supplied_answer)
            )
            content_changed = (
                bool(old.file_sha256) and old.file_sha256 != hashes[relative]
            )
            category_changed = old.category != question.category
            if answer_changed or content_changed or category_changed:
                reason_parts = []
                if answer_changed:
                    reason_parts.append("answer-changed")
                if content_changed:
                    reason_parts.append("content-changed")
                if category_changed:
                    reason_parts.append("category-changed")
                changes.append(
                    BankChange(
                        "UPDATE",
                        old,
                        question,
                        new_answer=supplied_answer if answer_changed else "",
                        reason="+".join(reason_parts),
                    )
                )

        for change in changes:
            if change.kind == "DELETE" or change.question is None:
                continue
            supplied = normalize_answer(
                supplied_answers.get(
                    normalize_relative_path(change.question.relative_path), ""
                )
            )
            if AnswerKeyRepository.validate(change.question, supplied):
                change.new_answer = supplied

        result.changes = changes
        if not changes:
            result.bank_version = previous_version
            if result.initialized and apply:
                summary = {"added": 0, "updated": 0, "deleted": 0}
                manifest = self._manifest_text(
                    subject.name, previous_version, old_entries, summary
                ).encode("utf-8")
                self._atomic_write(
                    versions_dir / f"answers.v{previous_version}.csv",
                    answers_path.read_bytes(),
                )
                self._atomic_write(
                    versions_dir / f"manifest.v{previous_version}.json", manifest
                )
                self._atomic_write(active_manifest_path, manifest)
                if self.database.recorded_bank_version(subject.name) is None:
                    self.database.apply_question_bank_update(
                        subject=subject.name,
                        bank_version=previous_version,
                        revisions=[asdict(entry) for entry in old_entries],
                        updates=[],
                        question_count=len(subject.questions),
                        added_count=0,
                        deleted_count=0,
                    )
            return result

        next_version = previous_version + 1
        result.bank_version = next_version
        if not apply:
            return result

        resolved_answers: dict[str, str] = {}
        for change in changes:
            if change.kind == "DELETE" or change.question is None:
                continue
            question = change.question
            relative = normalize_relative_path(question.relative_path)
            candidate = normalize_answer(
                change.new_answer or supplied_answers.get(relative, "")
            )
            preserve_move = (
                change.kind == "UPDATE"
                and change.old is not None
                and change.old.category == question.category
                and change.old.file_sha256 == hashes[relative]
                and AnswerKeyRepository.validate(question, change.old.answer)
            )
            # An explicit, valid approved correction wins even when the image
            # did not change. Preserve a moved answer only as a fallback.
            if preserve_move and not candidate:
                candidate = change.old.answer
            if not candidate or not AnswerKeyRepository.validate(question, candidate):
                try:
                    candidate = normalize_answer(self.answer_resolver(question))
                except (
                    ImportError,
                    OSError,
                    ValueError,
                    RuntimeError,
                ) as exc:
                    result.errors.append(f"{relative}: {exc}")
                    continue
            if not AnswerKeyRepository.validate(question, candidate):
                result.errors.append(f"Không nhận diện được đáp án hợp lệ: {relative}")
                continue
            change.new_answer = candidate
            resolved_answers[relative] = candidate

        if result.errors:
            return result

        updates_by_path = {
            normalize_relative_path(change.question.relative_path): change
            for change in changes
            if change.kind == "UPDATE" and change.question is not None
        }
        adds_by_path = {
            normalize_relative_path(change.question.relative_path): change
            for change in changes
            if change.kind == "ADD" and change.question is not None
        }
        new_entries: list[BankEntry] = []
        revisions: list[BankEntry] = []
        for relative, question in current.items():
            if relative in updates_by_path:
                change = updates_by_path[relative]
                assert change.old is not None
                entry = BankEntry(
                    logical_id=change.old.logical_id,
                    revision=change.old.revision + 1,
                    question_id=question.id,
                    bank_version=next_version,
                    relative_path=relative,
                    category=question.category,
                    answer=resolved_answers[relative],
                    file_sha256=hashes[relative],
                    supersedes_question_id=change.old.question_id,
                )
                revisions.append(BankEntry(**{**asdict(change.old), "active": False}))
            elif relative in adds_by_path:
                entry = BankEntry(
                    logical_id=question.id,
                    revision=1,
                    question_id=question.id,
                    bank_version=next_version,
                    relative_path=relative,
                    category=question.category,
                    answer=resolved_answers[relative],
                    file_sha256=hashes[relative],
                )
            else:
                old = old_active[relative]
                entry = BankEntry(
                    **{
                        **asdict(old),
                        "relative_path": relative,
                        "category": question.category,
                        "question_id": question.id,
                        "file_sha256": hashes[relative],
                        "active": True,
                    }
                )
            new_entries.append(entry)
            revisions.append(entry)

        for change in changes:
            if change.kind == "DELETE" and change.old is not None:
                revisions.append(BankEntry(**{**asdict(change.old), "active": False}))

        summary = {
            "added": len(result.added),
            "updated": len(result.updated),
            "deleted": len(result.deleted),
        }
        manifest_bytes = self._manifest_text(
            subject.name, next_version, new_entries, summary
        ).encode("utf-8")
        answers_bytes = self._answers_bytes(new_entries)

        if result.initialized:
            initial_manifest = self._manifest_text(
                subject.name,
                previous_version,
                old_entries,
                {"added": 0, "updated": 0, "deleted": 0},
            ).encode("utf-8")
            self._atomic_write(
                versions_dir / f"answers.v{previous_version}.csv",
                answers_path.read_bytes(),
            )
            self._atomic_write(
                versions_dir / f"manifest.v{previous_version}.json", initial_manifest
            )
            if self.database.recorded_bank_version(subject.name) is None:
                self.database.apply_question_bank_update(
                    subject=subject.name,
                    bank_version=previous_version,
                    revisions=[asdict(entry) for entry in old_entries],
                    updates=[],
                    question_count=len(old_entries),
                    added_count=0,
                    deleted_count=0,
                )

        def finalize_files() -> None:
            files = {
                versions_dir / f"answers.v{next_version}.csv": answers_bytes,
                versions_dir / f"manifest.v{next_version}.json": manifest_bytes,
                versions_dir
                / f"changes.v{previous_version}-to-v{next_version}.csv": self._change_report_bytes(
                    changes
                ),
                answers_path: answers_bytes,
                active_manifest_path: manifest_bytes,
            }
            if pending_answers_path.exists():
                archived_pending_path = (
                    versions_dir / f"answers.pending.applied.v{next_version}.csv"
                )
                files[archived_pending_path] = pending_answers_path.read_bytes()
            self._atomic_write_batch(files)
            if pending_answers_path.exists():
                pending_answers_path.unlink()

        try:
            self.database.apply_question_bank_update(
                subject=subject.name,
                bank_version=next_version,
                revisions=[asdict(entry) for entry in revisions],
                updates=[
                    {
                        "old_question_id": change.old.question_id,
                        "new_question_id": change.question.id,
                        "relative_path": normalize_relative_path(
                            change.question.relative_path
                        ),
                        "category": change.question.category,
                        "answer": change.new_answer,
                    }
                    for change in result.updated
                    if change.old is not None and change.question is not None
                ],
                question_count=len(subject.questions),
                added_count=len(result.added),
                deleted_count=len(result.deleted),
                notification_changes=self._notification_change_rows(result.changes),
                finalize=finalize_files,
            )
        except OSError as exc:
            result.errors.append(f"Không ghi được answer bank v{next_version}: {exc}")
            LOGGER.exception(
                "Không ghi được answer bank %s v%d", subject.name, next_version
            )
            return result
        result.applied = True
        LOGGER.info(
            "%s: answer bank v%d -> v%d; add=%d update=%d delete=%d",
            subject.name,
            previous_version,
            next_version,
            len(result.added),
            len(result.updated),
            len(result.deleted),
        )
        return result

    def check(
        self, subjects: list[Subject], *, apply: bool = True
    ) -> list[BankUpdateResult]:
        return [self.check_subject(subject, apply=apply) for subject in subjects]


def stage_replacement_answer_history(
    previous_subject: Path, incoming_subject: Path, subject: str
) -> int | None:
    """Carry the device's version history into a verified replacement package.

    The package supplies the new questions and answers, but its own version
    directory must not reset or overwrite the local history. The caller stages
    this before swapping either subject directory.
    """
    previous_answers = previous_subject / AnswerKeyRepository.FILE_NAME
    previous_versions = previous_subject / VERSION_DIRECTORY
    active_manifest = previous_versions / ACTIVE_MANIFEST
    if not previous_answers.is_file():
        if active_manifest.exists():
            raise ValueError("Môn cũ có manifest nhưng thiếu answers.csv.")
        return None
    if previous_versions.is_symlink() or not active_manifest.is_file():
        raise ValueError(
            "Môn cũ chưa có answer version hợp lệ; hãy làm mới dữ liệu trước khi thay gói."
        )

    manifest_payload = json.loads(active_manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest_payload, dict):
        raise TypeError("Manifest answer version của môn cũ không hợp lệ.")
    version, _entries = QuestionBankUpdateChecker._load_manifest(active_manifest)
    manifest_subject = manifest_payload.get("subject")
    if version < 1 or manifest_subject != subject:
        raise ValueError("Manifest answer version của môn cũ không khớp môn đang thay.")
    snapshots = (
        previous_versions / f"answers.v{version}.csv",
        previous_versions / f"manifest.v{version}.json",
    )
    if any(path.is_symlink() or not path.is_file() for path in snapshots):
        raise ValueError("Môn cũ thiếu bản lưu answer version đang hoạt động.")
    if snapshots[1].read_bytes() != active_manifest.read_bytes():
        raise ValueError("Manifest answer version của môn cũ không nhất quán.")

    incoming_versions = incoming_subject / VERSION_DIRECTORY
    if incoming_versions.is_symlink():
        raise ValueError("Gói mới chứa answer_versions không an toàn.")
    if incoming_versions.exists():
        if not incoming_versions.is_dir():
            raise ValueError("Gói mới chứa answer_versions không hợp lệ.")
        shutil.rmtree(incoming_versions)
    shutil.copytree(previous_versions, incoming_versions)
    return version
