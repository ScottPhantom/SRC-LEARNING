# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

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
    a.binaries,
    a.datas,
    [],
    name="LuyenThiHinhAnh",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(project / "app" / "resources" / "brand" / "src-learning.ico") if sys.platform == "win32" else None,
)
