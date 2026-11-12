"""Preserve, round-trip verify, and GUI-smoke-test the macOS release ZIP.

Uses only Python's standard library and macOS tools. The GUI test launches the
extracted .app via LaunchServices with a fresh, temporary application profile;
it never reuses the developer's DATA, database, or existing app process.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import plistlib
import signal
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath


APP_NAME = "SRC Learning.app"
BUNDLE_ID = "io.srcproject.srclearning"


def bundle_manifest(app: Path) -> dict[str, tuple[str, str, int]]:
    """Record files, modes and symlink targets without following directory links."""
    result: dict[str, tuple[str, str, int]] = {}
    for directory, folders, files in os.walk(app, followlinks=False):
        for name in folders + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            relative = path.relative_to(app).as_posix()
            if stat.S_ISLNK(mode):
                # Symlink permission bits are not meaningful on macOS.
                result[relative] = ("symlink", os.readlink(path), 0)
            elif stat.S_ISDIR(mode):
                result[relative] = ("directory", "", stat.S_IMODE(mode))
            elif stat.S_ISREG(mode):
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                result[relative] = ("file", digest, stat.S_IMODE(mode))
            else:
                raise ValueError(f"Unsupported bundle entry: {relative}")
    return result


def validate_bundle(app: Path) -> Path:
    if app.name != APP_NAME or not app.is_dir() or app.is_symlink():
        raise ValueError(f"Expected an intact {APP_NAME} directory: {app}")
    with (app / "Contents" / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleIdentifier") != BUNDLE_ID:
        raise ValueError("Unexpected CFBundleIdentifier")
    name = info.get("CFBundleExecutable", "")
    if not name or Path(name).name != name:
        raise ValueError("Invalid CFBundleExecutable")
    executable = app / "Contents" / "MacOS" / name
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("Bundle executable is missing or not executable")
    for framework in (app / "Contents" / "Frameworks").rglob("*.framework"):
        if (framework / "Versions").is_dir():
            if not (framework / "Versions" / "Current").is_symlink():
                raise ValueError(f"Flattened framework link: {framework.name}")
    links = [p for p in app.rglob("*") if p.is_symlink()]
    if not links:
        raise ValueError("Bundle symlinks are missing (possibly flattened by upload)")
    root = app.resolve()
    for link in links:
        try:
            target = link.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"Broken or cyclic bundle symlink: {link}") from exc
        if not target.is_relative_to(root):
            raise ValueError(f"Symlink escapes bundle: {link}")
    return executable


def validate_archive(archive: Path) -> None:
    """Reject a missing .app wrapper or unsafe entries before invoking ditto."""
    found_bundle = False
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            # ZipInfo normalizes backslashes on Windows and truncates NULs.
            # Validate the original name before either normalization can hide it.
            original = entry.orig_filename
            path = PurePosixPath(original)
            if path.is_absolute() or ".." in path.parts or "\\" in original or "\x00" in original:
                raise ValueError(f"Unsafe archive path: {original!r}")
            if not path.parts or path.parts[0] not in {APP_NAME, "__MACOSX"}:
                raise ValueError(f"ZIP must retain the {APP_NAME} wrapper")
            if path.parts[0] == APP_NAME:
                found_bundle = True
            if stat.S_ISLNK(entry.external_attr >> 16):
                target = bundle.read(entry).decode("utf-8")
                target_path = PurePosixPath(target)
                if target_path.is_absolute():
                    raise ValueError(f"Absolute symlink in ZIP: {entry.filename}")
                # A relative link must stay inside its top-level bundle.
                depth = len(path.parts) - 1
                for part in target_path.parts:
                    depth += -1 if part == ".." else (0 if part == "." else 1)
                    if depth < 1:
                        raise ValueError(f"Symlink escapes ZIP bundle: {entry.filename}")
    if not found_bundle:
        raise ValueError(f"ZIP does not contain {APP_NAME}")


def package(app: Path, archive: Path) -> None:
    validate_bundle(app)
    if archive.exists():
        raise ValueError(f"Refusing to overwrite an existing release ZIP: {archive}")
    if archive.resolve().is_relative_to(app.resolve()):
        raise ValueError("Release ZIP must not be written inside its own app bundle")
    archive.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)],
        check=True,
    )
    validate_archive(archive)


def matching_pids(executable: Path) -> set[int]:
    """Match the exact executable path, not another user's SRC Learning process."""
    proc = ctypes.CDLL("/usr/lib/libproc.dylib")
    proc.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    proc.proc_pidpath.restype = ctypes.c_int
    output = subprocess.check_output(["/bin/ps", "-axo", "pid="], text=True)
    matches = set()
    for value in output.split():
        pid = int(value)
        buffer = ctypes.create_string_buffer(4096)
        if proc.proc_pidpath(pid, buffer, len(buffer)) > 0:
            if Path(os.fsdecode(buffer.value)).resolve() == executable.resolve():
                matches.add(pid)
    return matches


def visible_main_windows(pids: set[int]) -> list[dict[str, int]]:
    """Inspect only our own on-screen windows; exclude the small startup splash."""
    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    pointer = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [pointer, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = pointer
    cf.CFArrayGetCount.argtypes = [pointer]
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetValueAtIndex.argtypes = [pointer, ctypes.c_long]
    cf.CFArrayGetValueAtIndex.restype = pointer
    cf.CFDictionaryGetValue.argtypes = [pointer, pointer]
    cf.CFDictionaryGetValue.restype = pointer
    cf.CFNumberGetValue.argtypes = [pointer, ctypes.c_int, pointer]
    cf.CFNumberGetValue.restype = ctypes.c_bool
    cf.CFRelease.argtypes = [pointer]
    cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    cg.CGWindowListCopyWindowInfo.restype = pointer
    keys: dict[str, int] = {}

    def item(dictionary, key: str):
        if key not in keys:
            keys[key] = cf.CFStringCreateWithCString(None, key.encode(), 0x08000100)
        return cf.CFDictionaryGetValue(dictionary, keys[key])

    def number(value) -> int:
        result = ctypes.c_double()
        if not value or not cf.CFNumberGetValue(value, 13, ctypes.byref(result)):
            return -1
        return int(result.value)

    windows = cg.CGWindowListCopyWindowInfo(1 | 16, 0)
    if not windows:
        raise RuntimeError("No macOS window-server session is available for GUI testing")
    result = []
    try:
        for index in range(cf.CFArrayGetCount(windows)):
            window = cf.CFArrayGetValueAtIndex(windows, index)
            pid = number(item(window, "kCGWindowOwnerPID"))
            if pid not in pids or number(item(window, "kCGWindowLayer")) != 0:
                continue
            bounds = item(window, "kCGWindowBounds")
            if not bounds:
                continue
            width, height = number(item(bounds, "Width")), number(item(bounds, "Height"))
            if width >= 1000 and height >= 600:
                result.append({"pid": pid, "width": width, "height": height})
        return result
    finally:
        cf.CFRelease(windows)
        for key in keys.values():
            cf.CFRelease(key)


def smoke_launch(app: Path, state: Path, timeout: float = 40) -> dict:
    executable = validate_bundle(app).resolve()
    if matching_pids(executable):
        raise RuntimeError("The exact QA bundle is already running; refusing to reuse it")
    state.mkdir(parents=True)
    environment = os.environ.copy()
    environment.pop("QT_QPA_PLATFORM", None)  # This must be a real Cocoa window.
    started = time.monotonic()
    launcher = subprocess.Popen(
        ["/usr/bin/open", "-n", "-W", "--env", f"SRC_LEARNING_STATE_DIR={state}",
         "--env", "QT_QPA_PLATFORM=cocoa", "--stdout", str(state / "launch.stdout"),
         "--stderr", str(state / "launch.stderr"), str(app)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    windows: list[dict[str, int]] = []
    stable_since = None
    try:
        while time.monotonic() - started < timeout:
            if launcher.poll() is not None:
                stdout, stderr = launcher.communicate()
                raise RuntimeError(f"App exited before GUI verification: {stdout}{stderr}")
            pids = matching_pids(executable)
            windows = visible_main_windows(pids) if pids else []
            if windows:
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= 5:
                    break
            else:
                stable_since = None
            time.sleep(0.5)
        else:
            raise RuntimeError("No stable, on-screen main window appeared (splash is insufficient)")
        database = state / "study_progress.sqlite3"
        log_file = state / "study_app.log"
        if not database.is_file() or not log_file.is_file():
            raise RuntimeError("App did not initialize its isolated database and log")
        log = log_file.read_text(encoding="utf-8")
        if "Traceback (most recent call last)" in log or " CRITICAL " in log or " ERROR " in log:
            raise RuntimeError(f"Startup log contains an error:\n{log}")
        return {
            "launch_services": True,
            "qt_platform": "cocoa",
            "visible_main_windows": windows,
            "stable_window_seconds": 5,
            "isolated_profile_initialized": True,
            "startup_log": log,
            "cleanup": "SIGTERM of the exact temporary QA executable only",
        }
    finally:
        # Never kill by bundle ID or app name: the user's normal app may be open.
        for pid in matching_pids(executable):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            launcher.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            launcher.kill()
            launcher.communicate()
        if matching_pids(executable):
            raise RuntimeError("The temporary QA app did not stop; inspect it before retrying")


def verify(archive: Path, source_app: Path | None = None, launch: bool = False) -> dict:
    validate_archive(archive)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {"archive": archive.name, "sha256": digest, "size_bytes": archive.stat().st_size}
    with tempfile.TemporaryDirectory(prefix="src-learning-macos-qa-") as temporary:
        scratch = Path(temporary)
        subprocess.run(["/usr/bin/ditto", "-x", "-k", str(archive), str(scratch)], check=True)
        app = scratch / APP_NAME
        executable = validate_bundle(app)
        manifest = bundle_manifest(app)
        if source_app is not None and manifest != bundle_manifest(source_app):
            raise ValueError("Archive round-trip changed file contents, permissions or symlinks")
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
        report.update({
            "app_wrapper": app.name,
            "symlink_count": sum(entry[0] == "symlink" for entry in manifest.values()),
            "executable_permissions": oct(stat.S_IMODE(executable.stat().st_mode)),
            "architectures": subprocess.check_output(["/usr/bin/lipo", "-archs", str(executable)], text=True).strip(),
            "codesign_deep_strict": "passed (ad-hoc; not Developer ID notarization)",
            "source_round_trip": source_app is not None,
            "macos": subprocess.check_output(["/usr/bin/sw_vers", "-productVersion"], text=True).strip(),
        })
        if launch:
            report["gui_smoke"] = smoke_launch(app, scratch / "qa-profile")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    pack = actions.add_parser("package")
    pack.add_argument("--app", type=Path, required=True)
    pack.add_argument("--archive", type=Path, required=True)
    check = actions.add_parser("verify")
    check.add_argument("--archive", type=Path, required=True)
    check.add_argument("--source-app", type=Path)
    check.add_argument("--launch", action="store_true")
    check.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Packaging and release verification require macOS")
    if arguments.action == "package":
        package(arguments.app.resolve(), arguments.archive.resolve())
        return 0
    report = verify(arguments.archive.resolve(), arguments.source_app, arguments.launch)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if arguments.report:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(rendered, encoding="utf-8")
    arguments.archive.with_suffix(arguments.archive.suffix + ".sha256").write_text(
        f"{report['sha256']}  {arguments.archive.name}\n", encoding="utf-8"
    )
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
