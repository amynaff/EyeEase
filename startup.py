"""
startup.py — "launch at login", per platform.

macOS uses a LaunchAgent: a small plist in ~/Library/LaunchAgents that
launchd reads at login. Windows uses the per-user Run key in the registry.
Both are user-level — neither needs admin rights, and both are a single
file/value that the user can delete by hand if this app ever misbehaves.

Nothing here is mirrored into the settings file on purpose. The OS is the
only real answer to "does this launch at login": a saved flag can drift out
of sync the moment someone removes the login item themselves, and then the
switch in the panel would be claiming something untrue. is_enabled() always
goes and looks.
"""

import os
import subprocess
import sys
from pathlib import Path

LABEL = "com.eyeease.launcher"
APP_NAME = "EyeEase"

SYSTEM = sys.platform  # 'darwin', 'win32', ...

LAUNCH_AGENT_PATH = (
    Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_supported() -> bool:
    return SYSTEM in ("darwin", "win32")


def launch_command():
    """The argv that should be run at login.

    Frozen by PyInstaller, sys.executable *is* the app binary (inside
    EyeEase.app/Contents/MacOS on macOS), so it launches on its own. Running
    from source it's the interpreter, which needs main.py handed to it.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]
    main_py = Path(__file__).resolve().parent / "main.py"
    return [sys.executable, str(main_py)]


# -- macOS --------------------------------------------------------------


def _macos_is_enabled() -> bool:
    return LAUNCH_AGENT_PATH.exists()


def _macos_enable() -> bool:
    import plistlib

    plist = {
        "Label": LABEL,
        "ProgramArguments": launch_command(),
        "RunAtLoad": True,
        # Deliberately no KeepAlive: with it, quitting from the tray would
        # just have launchd start the app straight back up.
        "ProcessType": "Interactive",
    }
    try:
        LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LAUNCH_AGENT_PATH, "wb") as f:
            plistlib.dump(plist, f)
    except OSError:
        return False

    # The plist is not loaded into launchd here on purpose. launchd reads
    # ~/Library/LaunchAgents at login, which is exactly when this should
    # take effect; loading it now would immediately start a second copy of
    # the app on top of the one the user is looking at.
    return LAUNCH_AGENT_PATH.exists()


def _macos_disable() -> bool:
    try:
        LAUNCH_AGENT_PATH.unlink(missing_ok=True)
    except OSError:
        return False
    # If a previous login already loaded it, drop it from launchd too so the
    # setting doesn't survive until the next restart. Failure is fine — it
    # just means it wasn't loaded.
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"],
        capture_output=True,
        check=False,
    )
    return not LAUNCH_AGENT_PATH.exists()


# -- Windows ------------------------------------------------------------


def _windows_value() -> str:
    return subprocess.list2cmdline(launch_command())


def _windows_is_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except (FileNotFoundError, OSError):
        return False


def _windows_enable() -> bool:
    import winreg

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _windows_value())
    except OSError:
        return False
    return _windows_is_enabled()


def _windows_disable() -> bool:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        return True  # already gone
    except OSError:
        return False
    return not _windows_is_enabled()


# -- public -------------------------------------------------------------


def is_enabled() -> bool:
    try:
        if SYSTEM == "darwin":
            return _macos_is_enabled()
        if SYSTEM == "win32":
            return _windows_is_enabled()
    except Exception:
        pass
    return False


def enable() -> bool:
    """True only if the login item is verifiably in place afterwards."""
    try:
        if SYSTEM == "darwin":
            return _macos_enable()
        if SYSTEM == "win32":
            return _windows_enable()
    except Exception:
        pass
    return False


def disable() -> bool:
    try:
        if SYSTEM == "darwin":
            return _macos_disable()
        if SYSTEM == "win32":
            return _windows_disable()
    except Exception:
        pass
    return False
