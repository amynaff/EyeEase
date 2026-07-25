# -*- mode: python ; coding: utf-8 -*-
#
# Build on Windows (PyInstaller can't cross-compile):
#   pip install -r requirements.txt pyinstaller
#   pyinstaller --noconfirm eyeease-windows.spec
#
# Produces dist/EyeEase.exe — a single portable executable, no console
# window (console=False below), matching how RedShift ships on Windows.
#
# PyInstaller can't cross-compile: it silently builds for whatever OS it
# runs on (no error, just a same-platform binary with the wrong name), so
# this guard stops it from being run by mistake on macOS/Linux.
import platform
if platform.system() != "Windows":
    raise SystemExit(
        "eyeease-windows.spec must be run with PyInstaller on Windows "
        f"(detected {platform.system()}) — PyInstaller cannot cross-compile."
    )

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/icon.png", "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EyeEase",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
)
