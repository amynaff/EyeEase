"""update_check.py — a manual, user-initiated version check.

EyeEase's whole pitch is that it never touches the network. This is the one
exception, and it only runs when someone clicks "Check for updates" in the
tray menu — never on launch, never on a timer, nothing phoned home without
being asked.

Runs entirely off Tk: the HTTP request happens on a background thread, and
the result is delivered via NSUserNotificationCenter rather than pystray's
own notify() — that shells out to `osascript -e 'display notification'`,
which turned out to be silently broken on at least one real machine (the
"Allow Notifications" toggle for Script Editor was on, Focus was off, and
it still never posted). NSUserNotificationCenter is older and technically
deprecated in favor of UserNotifications.framework, but it delivers under
the app's own identity with no extra pyobjc dependency and no separate
authorization prompt, and it actually works where the AppleScript bridge
didn't. Either way this is a plain Foundation/AppKit call, not a Tk one —
see tray.py's on_show/on_quit for what happens when a tray callback touches
Tk directly instead.
"""

import json
import threading
import urllib.error
import urllib.request
import webbrowser

from version import APP_VERSION

RELEASES_API = "https://api.github.com/repos/amynaff/EyeEase/releases/latest"
RELEASES_PAGE = "https://github.com/amynaff/EyeEase/releases/latest"


def _version_tuple(version_string):
    parts = []
    for piece in version_string.split("."):
        digits = "".join(c for c in piece if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _notify(message):
    try:
        from Foundation import NSUserNotification, NSUserNotificationCenter

        note = NSUserNotification.alloc().init()
        note.setTitle_("EyeEase")
        note.setInformativeText_(message)
        NSUserNotificationCenter.defaultUserNotificationCenter().deliverNotification_(
            note
        )
    except ImportError:
        pass  # no pyobjc: the check still ran, just nothing to show for it


def check_for_updates():
    def worker():
        try:
            request = urllib.request.Request(
                RELEASES_API, headers={"Accept": "application/vnd.github+json"}
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.load(response)
            latest = data.get("tag_name", "").lstrip("v")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            _notify("Couldn't reach GitHub to check — try again later.")
            return

        if not latest:
            _notify("Couldn't read the latest version.")
        elif _version_tuple(latest) > _version_tuple(APP_VERSION):
            _notify(f"Version {latest} is out — opening the download page.")
            webbrowser.open(RELEASES_PAGE)
        else:
            _notify(f"You're on the latest version ({APP_VERSION}).")

    threading.Thread(target=worker, daemon=True).start()
