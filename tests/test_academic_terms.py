from __future__ import annotations

from pathlib import Path

from app.domain.models import Subject
from app.services.academic_terms import group_subjects_by_term, resolve_academic_term


def subject(root: Path, name: str) -> Subject:
    path = root / name
    path.mkdir(exist_ok=True)
    return Subject(name=name, path=path)


def test_existing_subjects_are_grouped_by_2026_terms(tmp_path: Path) -> None:
    subjects = [
        subject(tmp_path, name)
        for name in ("SSG105", "ITE303c", "DAP391m", "AIL303m", "CPV301")
    ]
    groups = group_subjects_by_term(subjects)
    assert [(term.code, [item.name for item in items]) for term, items in groups] == [
        ("FA26", ["AIL303m", "CPV301", "DAP391m", "SSG105"]),
        ("SU26", ["ITE303c"]),
    ]


def test_package_metadata_supports_2027_and_later_without_code_change(
    tmp_path: Path,
) -> None:
    spring = subject(tmp_path, "NEW101")
    (spring.path / "academic_term.json").write_text(
        '{"year": 2027, "semester": "Spring"}', encoding="utf-8"
    )
    summer = subject(tmp_path, "NEW201")
    (summer.path / "academic_term.json").write_text(
        '{"year": 2027, "semester": "SU"}', encoding="utf-8"
    )
    fall = subject(tmp_path, "NEW301")
    (fall.path / "academic_term.json").write_text(
        '{"year": 2027, "semester": "FA"}', encoding="utf-8"
    )
    unknown = subject(tmp_path, "OTHER101")
    known_override = subject(tmp_path, "AIL303m")
    (known_override.path / "academic_term.json").write_text(
        '{"year": 2027, "semester": "FA"}', encoding="utf-8"
    )
    previous_year = subject(tmp_path, "ITE303c")
    groups = group_subjects_by_term(
        [unknown, previous_year, fall, summer, spring, known_override]
    )
    assert [term.code if term else None for term, _ in groups] == [
        "FA27", "SU27", "SP27", "SU26", None
    ]
    assert [item.name for item in groups[0][1]] == ["AIL303m", "NEW301"]
    assert [item.name for item in groups[4][1]] == ["OTHER101"]


def test_invalid_academic_metadata_cannot_hide_subject(tmp_path: Path) -> None:
    unknown = subject(tmp_path, "OTHER101")
    (unknown.path / "academic_term.json").write_text(
        '{"year": 2027, "semester": "WINTER"}', encoding="utf-8"
    )
    assert resolve_academic_term(unknown) is None
    known = subject(tmp_path, "ITE303c")
    (known.path / "academic_term.json").write_text("{invalid", encoding="utf-8")
    assert resolve_academic_term(known).code == "SU26"


def test_trial_subjects_follow_base_term_unless_package_overrides_it(
    tmp_path: Path,
) -> None:
    ail_trial = subject(tmp_path, "AIL303M_t")
    assert resolve_academic_term(ail_trial).code == "FA26"
    (ail_trial.path / "academic_term.json").write_text(
        '{"year": 2027, "semester": "SP"}', encoding="utf-8"
    )
    assert resolve_academic_term(ail_trial).code == "SP27"
    assert resolve_academic_term(subject(tmp_path, "UNKNOWN_t")) is None
