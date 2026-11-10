"""Academic-term labels for installed subject packages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.domain.models import Subject

TERM_ORDER = {"SP": 0, "SU": 1, "FA": 2}
TERM_NAMES = {"SP": "Spring", "SU": "Summer", "FA": "Fall"}
TERM_ALIASES = {"SPRING": "SP", "SUMMER": "SU", "FALL": "FA"}
MAX_METADATA_BYTES = 2048


@dataclass(frozen=True, slots=True)
class AcademicTerm:
    year: int
    semester: str

    @property
    def code(self) -> str:
        return f"{self.semester}{self.year % 100:02d}"

    @property
    def label(self) -> str:
        return f"{self.code} · {TERM_NAMES[self.semester]} {self.year}"


# Existing packages predate academic_term.json. An explicit package file wins
# if a course is offered again in a later term.
KNOWN_TERMS = {
    "ITE303C": AcademicTerm(2026, "SU"),
    "AIL303M": AcademicTerm(2026, "FA"),
    "CPV301": AcademicTerm(2026, "FA"),
    "DAP391M": AcademicTerm(2026, "FA"),
    "SSG105": AcademicTerm(2026, "FA"),
}


def _read_package_term(subject_path: Path) -> AcademicTerm | None:
    metadata = subject_path / "academic_term.json"
    if metadata.is_symlink() or not metadata.is_file():
        return None
    try:
        with metadata.open("rb") as handle:
            raw = handle.read(MAX_METADATA_BYTES + 1)
        if len(raw) > MAX_METADATA_BYTES:
            return None
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        year = payload.get("year")
        semester = payload.get("semester")
        if type(year) is not int or not 2000 <= year <= 2099:
            return None
        if not isinstance(semester, str):
            return None
        semester = semester.strip().upper()
        semester = TERM_ALIASES.get(semester, semester)
        if semester not in TERM_ORDER:
            return None
        return AcademicTerm(year, semester)
    except (OSError, UnicodeError, ValueError, TypeError):
        return None


def resolve_academic_term(subject: Subject) -> AcademicTerm | None:
    """Use package metadata, then the legacy mapping (also for ``*_t`` copies)."""
    name = subject.name.upper().removesuffix("_T")
    return _read_package_term(subject.path) or KNOWN_TERMS.get(name)


def group_subjects_by_term(
    subjects: list[Subject],
) -> list[tuple[AcademicTerm | None, list[Subject]]]:
    """Show newest years and terms first; keep unclassified courses last."""
    groups: dict[AcademicTerm | None, list[Subject]] = {}
    for subject in subjects:
        groups.setdefault(resolve_academic_term(subject), []).append(subject)
    ordered_terms = sorted(
        (term for term in groups if term is not None),
        key=lambda term: (term.year, TERM_ORDER[term.semester]),
        reverse=True,
    )
    result = [
        (term, sorted(groups[term], key=lambda subject: subject.name.casefold()))
        for term in ordered_terms
    ]
    if None in groups:
        result.append(
            (None, sorted(groups[None], key=lambda subject: subject.name.casefold()))
        )
    return result
