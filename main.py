"""
main.py — starts the panel and the menu-bar icon.

Also installs the handlers that make quitting give the screen back. The tray
menu's Quit runs on_close(), but that's only one of the ways this app dies:
a logout, a Force Quit, a `kill`, or Ctrl-C from a terminal all skip it, and
the backlight would stay pinned at 100% (see EyeEaseApp.restore_display).

Signal handlers only run between bytecodes, and Tk's mainloop blocks in C —
so this relies on the app's own after() timers giving Python the floor every
couple of seconds. That's what makes the handler below fire at all.
"""

import signal
import sys

from app_ui import EyeEaseApp
from tray import run_tray


def main():
    app = EyeEaseApp()
    app.protocol("WM_DELETE_WINDOW", app.withdraw)  # closing the panel just hides it

    def on_signal(_signum, _frame):
        app.restore_display()
        sys.exit(0)

    for received in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(received, on_signal)
        except (ValueError, OSError):
            # Not every signal exists on every platform; a missing one is
            # one fewer exit path covered, not a reason to fail to start.
            pass

    run_tray(app)
    app.mainloop()


if __name__ == "__main__":
    main()
