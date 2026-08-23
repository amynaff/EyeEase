"""
tray.py — a small icon in the menu bar (Mac) / system tray (Windows) that
shows/hides the control panel, matching how RedShift and EyeEase both live
in the tray rather than the dock/taskbar.
"""

import sys

import pystray

from brand import BLUE, LENS, disc_icon
from update_check import check_for_updates

# Big enough that both menu bars downsample it cleanly; small enough that
# redrawing it on every on/off click costs nothing worth measuring.
TRAY_ICON_SIZE = 64


def make_icon_image(is_on: bool):
    """The tray mark in the colour of the current state.

    Amber while the app is easing the screen, blue while it isn't — blue
    being the light that gets through when nothing is filtering it. Drawn
    from brand.disc_icon() rather than loaded from assets/icon.png, because
    a PNG on disk can only ever be one of the two states.
    """
    return disc_icon(TRAY_ICON_SIZE, LENS if is_on else BLUE)


def run_tray(app):
    """app is the EyeEaseApp instance (a customtkinter window)."""

    def on_show(icon, item):
        # Setting a plain attribute here, not calling app.after() — this
        # callback runs on AppKit's own menu-tracking dispatch, not in
        # Tcl's callback chain, and a direct .after() call from here
        # corrupts _tkinter's saved thread state and aborts the process a
        # moment later. app_ui.py's _start_tray_polling() picks this up.
        app._tray_request = "show"

    def on_quit(icon, item):
        icon.stop()
        app._tray_request = "quit"

    def on_check_for_updates(icon, item):
        # Safe to call straight from this callback, unlike on_show/on_quit
        # above: it only starts a background thread and, later, posts a
        # notification directly — not a Tk or AppKit call routed through
        # this callback's own thread. See update_check.py's module
        # docstring for why it's NSUserNotificationCenter and not
        # pystray's own notify().
        check_for_updates()

    icon = pystray.Icon(
        "eyeease",
        make_icon_image(app.settings["is_on"]),
        "EyeEase",
        menu=pystray.Menu(
            pystray.MenuItem("Show panel", on_show, default=True),
            pystray.MenuItem("Check for updates", on_check_for_updates),
            pystray.MenuItem("Quit", on_quit),
        ),
    )

    # On macOS, pystray's icon.run() calls NSApplication.run(), which must
    # happen on the main thread — the same thread tkinter's mainloop already
    # drives. run_detached() just registers the status item and relies on
    # tkinter's mainloop to keep pumping the shared NSApplication event loop.
    icon.run_detached()

    # Hand the icon back to the app so the mark can follow the on/off state.
    # Done here rather than in main.py because run_detached() is the point
    # after which the status item exists and can be re-drawn.
    app.attach_tray(icon)
    _restore_display_on_terminate(app)
    _hide_from_dock(app)
    return icon


def _hide_from_dock(app):
    """Put the app back in the menu bar, where LSUIElement asked for it.

    The bundle sets LSUIElement and macOS honours it — then Tk takes it
    back. tkMacOSXInit.c's applicationDidFinishLaunching: calls
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular]
    unconditionally, with no check for LSUIElement, so a Tk app gets a Dock
    icon and a Cmd-Tab entry however the bundle is configured.

    Deferred, because finishLaunching runs asynchronously — Tk's own source
    calls that race out. Setting the policy before Tk's override lands would
    only be overridden in turn. Staggered past app_ui.py's _strip_chrome
    (80ms) rather than sharing its slot.
    """
    if sys.platform != "darwin":
        return

    def apply():
        try:
            from AppKit import (
                NSApplication,
                NSApplicationActivationPolicyAccessory,
            )
            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory
            )
        except (ImportError, AttributeError):
            # No pyobjc: a stray Dock icon, not a broken app.
            pass

    app.after(120, apply)


def force_redraw(icon):
    """Ask the status item to repaint after its image has been swapped.

    pystray sets the new NSImage on the button and stops, which is enough
    when AppKit is running its own event loop. Here it isn't: run_detached()
    hands the loop to tkinter's mainloop, so a button whose image changed
    outside AppKit's own drawing cycle can sit there showing the old one —
    which is what "the icon is still amber when it's off" looks like.

    Reaches into pystray's internals, so it fails quietly: a status item
    that repaints a moment late is worth far less than a crash.
    """
    if sys.platform != "darwin":
        return
    try:
        icon._status_item.button().setNeedsDisplay_(True)
    except (AttributeError, TypeError):
        pass


def _restore_display_on_terminate(app):
    """Catch the one way of quitting that skips every Python exit path.

    A quit Apple Event — what a logout, a Force Quit, or `osascript -e 'quit
    app "EyeEase"'` sends — tears the process down through NSApplication
    without running `atexit` handlers or delivering SIGTERM. Measured on a
    build: both were installed, neither fired, and the backlight stayed
    pinned at 100% with the user's own level never restored.

    NSApplication does post this notification on its way out, and pystray
    has already stood an NSApplication up by this point, so there's
    something to observe. This is the only hook that covers that exit.

    The returned token is parked on the app because NSNotificationCenter
    doesn't retain block observers — dropping it unregisters the observer.
    """
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplicationWillTerminateNotification
        from Foundation import NSNotificationCenter
    except ImportError:
        return  # no pyobjc: one fewer exit path covered, not a failure

    app.terminate_observer = (
        NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            NSApplicationWillTerminateNotification,
            None,
            None,
            lambda _notification: app.restore_display(),
        )
    )
