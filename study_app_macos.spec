# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project = Path(SPECPATH)

a = Analysis(
    [str(project / "main.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[
        (str(project / "app" / "ui" / "assets"), "app/ui/assets"),
        (str(project / "app" / "resources" / "brand"), "app/resources/brand"),
        (
            str(project / "app" / "resources" / "data_manifest.json"),
            "app/resources",
        ),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["cv2", "pytesseract"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SRC Learning",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
collect = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="SRC Learning",
)
app = BUNDLE(
    collect,
    name="SRC Learning.app",
    icon=str(project / "app" / "resources" / "brand" / "src-learning.icns"),
    bundle_identifier="io.srcproject.srclearning",
    info_plist={
        "CFBundleDisplayName": "SRC Learning",
        "NSHighResolutionCapable": True,
    },
)
