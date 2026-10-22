# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from gaubenmaster.version import __version__

parts = tuple(int(part) for part in __version__.split("."))
file_version = (parts + (0, 0, 0, 0))[:4]
comma = ", ".join(str(part) for part in file_version)
version_file = Path(SPECPATH) / "version_info.txt"
version_file.write_text(
    f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({comma}),
    prodvers=({comma}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040704e4',
        [StringStruct('CompanyName', 'Lukas Sonderegger'),
         StringStruct('FileDescription', 'GaubenMaster2'),
         StringStruct('FileVersion', '{__version__}'),
         StringStruct('InternalName', 'GaubenMaster2'),
         StringStruct('OriginalFilename', 'GaubenMaster2.exe'),
         StringStruct('ProductName', 'GaubenMaster2'),
         StringStruct('ProductVersion', '{__version__}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1031, 1252])])
  ]
)
""",
    encoding="utf-8",
)

onefile = os.environ.get("GM_ONEFILE") == "1"
excludes = [
    "unittest",
    "pydoc",
    "doctest",
    "test",
    "setuptools",
    "pip",
    "wheel",
    "distutils",
    "lib2to3",
    "tkinter.test",
]

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

common = dict(
    name="GaubenMaster2",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico"),
    version=str(version_file),
)

if onefile:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        runtime_tmpdir=None,
        **common,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        **common,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="GaubenMaster2",
    )
