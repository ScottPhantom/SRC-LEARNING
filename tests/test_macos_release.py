from __future__ import annotations

import os
import plistlib
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools.macos_release import (
    APP_NAME,
    BUNDLE_ID,
    bundle_manifest,
    package,
    validate_archive,
    validate_bundle,
)


def make_app(root: Path) -> Path:
    app = root / APP_NAME
    executable = app / "Contents" / "MacOS" / "SRC Learning"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fake executable for structural tests")
    executable.chmod(0o755)
    with (app / "Contents" / "Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleIdentifier": BUNDLE_ID, "CFBundleExecutable": executable.name}, stream)
    framework = app / "Contents" / "Frameworks" / "QtCore.framework"
    (framework / "Versions" / "5").mkdir(parents=True)
    (framework / "Versions" / "5" / "QtCore").write_bytes(b"framework")
    try:
        (framework / "Versions" / "Current").symlink_to("5", target_is_directory=True)
        (framework / "QtCore").symlink_to("Versions/Current/QtCore")
    except OSError:
        pytest.skip("Creating symlinks requires privileges on this Windows runner")
    return app


def test_bundle_manifest_preserves_modes_and_link_targets(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    validate_bundle(app)
    manifest = bundle_manifest(app)
    assert manifest["Contents/Frameworks/QtCore.framework/Versions/Current"] == ("symlink", "5", 0)
    assert "Contents/Frameworks/QtCore.framework/Versions/Current/QtCore" not in manifest
    before = manifest["Contents/MacOS/SRC Learning"]
    (app / "Contents" / "MacOS" / "SRC Learning").write_bytes(b"different contents")
    assert bundle_manifest(app)["Contents/MacOS/SRC Learning"] != before


def test_bundle_rejects_missing_wrapper(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="intact"):
        validate_bundle(tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="Windows does not model POSIX execute bits")
def test_bundle_rejects_lost_executable_mode(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    (app / "Contents" / "MacOS" / "SRC Learning").chmod(0o644)
    with pytest.raises(ValueError, match="not executable"):
        validate_bundle(app)


def test_bundle_rejects_flattened_framework_link(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    current = app / "Contents" / "Frameworks" / "QtCore.framework" / "Versions" / "Current"
    current.unlink()
    current.mkdir()
    with pytest.raises(ValueError, match="Flattened framework"):
        validate_bundle(app)


def test_bundle_rejects_links_outside_bundle(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    (app / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes bundle"):
        validate_bundle(app)


@pytest.mark.parametrize("entry", ["Contents/Info.plist", "../SRC Learning.app/evil", "/SRC Learning.app/evil", "SRC Learning.app/../evil", "SRC Learning.app\\evil"])
def test_archive_rejects_lost_wrapper_and_unsafe_paths(tmp_path: Path, entry: str) -> None:
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(entry, b"data")
    with pytest.raises(ValueError):
        validate_archive(archive)


@pytest.mark.parametrize("target", ["/tmp/outside", "../../outside"])
def test_archive_rejects_escaping_symlink(tmp_path: Path, target: str) -> None:
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        link = zipfile.ZipInfo(f"{APP_NAME}/Contents/escape")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(link, target)
    with pytest.raises(ValueError, match="symlink|Symlink"):
        validate_archive(archive)


def test_archive_accepts_bundle_and_resource_forks(tmp_path: Path) -> None:
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(f"{APP_NAME}/Contents/Info.plist", b"data")
        bundle.writestr(f"__MACOSX/{APP_NAME}/._Contents", b"resource fork")
    validate_archive(archive)


def test_archive_rejects_empty_zip(tmp_path: Path) -> None:
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w"):
        pass
    with pytest.raises(ValueError, match="does not contain"):
        validate_archive(archive)


@pytest.mark.skipif(sys.platform != "darwin", reason="ditto is a macOS tool")
def test_ditto_round_trip_preserves_bundle_wrapper_and_symlinks(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    archive = tmp_path / "release.zip"
    package(app, archive)
    unpacked = tmp_path / "extracted"
    subprocess.run(["/usr/bin/ditto", "-x", "-k", str(archive), str(unpacked)], check=True)
    restored = unpacked / APP_NAME
    validate_bundle(restored)
    assert bundle_manifest(restored) == bundle_manifest(app)


def test_package_does_not_overwrite_existing_archive(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    archive = tmp_path / "release.zip"
    archive.write_bytes(b"keep this existing release")
    with pytest.raises(ValueError, match="overwrite"):
        package(app, archive)
    assert archive.read_bytes() == b"keep this existing release"
