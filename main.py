"""
main.py — starts the panel and the menu-bar icon.

Refuses to start a second copy on top of a running one (see singleton.py),
and asks the running one to show itself instead.

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

import singleton
from app_ui import EyeEaseApp
from tray import run_tray

# How often to check whether a later launch asked for the panel. Short
# enough that a double-click feels answered, long enough to be free.
SHOW_POLL_MS = 500


def main():
    # Before EyeEaseApp, which starts touching gamma and the backlight the
    # moment it exists — the thing a second copy must not do.
    if not singleton.acquire():
        singleton.show_existing()
        return

    singleton.install_show_handler()

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

    def poll_show_requests():
        if singleton.take_show_request():
            app.show_panel()
        app.after(SHOW_POLL_MS, poll_show_requests)

    app.after(SHOW_POLL_MS, poll_show_requests)

    run_tray(app)
    app.mainloop()


if __name__ == "__main__":
    main()
