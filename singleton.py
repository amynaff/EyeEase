"""
singleton.py — one running copy of EyeEase, not two.

Nothing stopped a second launch before this, and two copies is not a
cosmetic problem: both of them drive the gamma ramp and the backlight on a
timer, so whichever one fires last decides what the screen looks like and
the sliders in the panel you are touching stop matching what you see.
Quitting one of them is worse than leaving both — restore_display() hands
the screen back while the other copy is still holding its own override.

Two ordinary ways to end up there: the LaunchAgent starts a copy at login
and you open the .app by hand as well, or a dist/ build from release.sh is
sitting next to the installed one in /Applications and you launch whichever
Spotlight offers first.

The lock is an OS file lock rather than a "is this PID still alive?" check
on a pidfile. The kernel drops it when the process dies, however it dies,
so a Force Quit, a crash, or a logout cannot leave a stale lock behind that
stops the app from ever starting again.
"""

import os
import signal
import sys
from pathlib import Path

# Alongside ~/.eyeease_settings.json, for the same reason it lives there:
# one user, one home directory, no install-location guessing.
LOCK_PATH = Path.home() / ".eyeease.lock"

SYSTEM = sys.platform

# The signal a second launch uses to say "you're already running — show
# yourself". POSIX only; Windows has no equivalent, so there a second launch
# just exits quietly.
SHOW_SIGNAL = getattr(signal, "SIGUSR1", None)

# Module-level on purpose. The lock lasts exactly as long as the file object
# is open, so a local in acquire() would be garbage-collected on return and
# hand the lock straight back.
_handle = None

_show_requested = False


if SYSTEM == "win32":
    import msvcrt

    def _take_lock(handle):
        # Locks one byte at the current position, so seek first — with the
        # file opened "a+" the position starts at the end, and two processes
        # appending would lock different bytes and both succeed.
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

else:
    import fcntl

    def _take_lock(handle):
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def acquire() -> bool:
    """Take the lock, or report that another copy already holds it.

    Returns True on failure to even open the lock file. An unwritable home
    directory is a strange machine, not a reason to refuse to start — the
    worst case is the old behavior, and the old behavior ran.
    """
    global _handle

    try:
        handle = open(LOCK_PATH, "a+")
    except OSError:
        return True

    try:
        _take_lock(handle)
    except OSError:
        # Held by the copy that is already running.
        handle.close()
        return False

    _handle = handle
    _write_pid(handle)
    return True


def _write_pid(handle):
    """Record our PID so a second launch knows who to poke.

    Windows keeps its byte-0 lock on this file and has no signal to send
    anyway, so writing there would only risk disturbing the lock for a value
    nothing reads.
    """
    if SYSTEM == "win32":
        return
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
    except OSError:
        # We hold the lock either way, which is the part that matters.
        pass


def show_existing() -> bool:
    """Ask the copy that is already running to bring its panel up.

    Without this a second launch would look like a broken app: you
    double-click the icon and nothing whatsoever happens, because the only
    instance is sitting in the tray where you left it.
    """
    if SHOW_SIGNAL is None:
        return False

    try:
        pid = int(LOCK_PATH.read_text().strip())
    except (OSError, ValueError):
        return False

    try:
        os.kill(pid, SHOW_SIGNAL)
    except OSError:
        return False
    return True


def install_show_handler():
    """Listen for the signal a later launch sends.

    The handler only sets a flag. Signal handlers interrupt Python wherever
    it happens to be, which may be inside a Tk callback, and Tk is not
    reentrant — so the panel is raised from the mainloop instead, by whoever
    polls take_show_request().
    """
    if SHOW_SIGNAL is None:
        return

    def on_show(_signum, _frame):
        global _show_requested
        _show_requested = True

    try:
        signal.signal(SHOW_SIGNAL, on_show)
    except (ValueError, OSError):
        # One fewer convenience, not a reason to fail to start.
        pass


def take_show_request() -> bool:
    """True once per signal received, and clears the request."""
    global _show_requested
    if not _show_requested:
        return False
    _show_requested = False
    return True
