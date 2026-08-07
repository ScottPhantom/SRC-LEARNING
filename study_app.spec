# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project = Path(SPECPATH)

a = Analysis(
    [str(project / "main.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[],
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
)
