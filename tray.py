"""
tray.py — a small icon in the menu bar (Mac) / system tray (Windows) that
shows/hides the control panel, matching how RedShift and EyeEase both live
in the tray rather than the dock/taskbar.
"""

import sys

import pystray

from brand import BLUE, LENS, disc_icon

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
        # show_panel() rather than deiconify(): the panel is borderless, and
        # restoring one without raising it looks exactly like a click that
        # did nothing.
        app.after(0, app.show_panel)

    def on_quit(icon, item):
        icon.stop()
        app.after(0, app.on_close)

    icon = pystray.Icon(
        "eyeease",
        make_icon_image(app.settings["is_on"]),
        "EyeEase",
        menu=pystray.Menu(
            pystray.MenuItem("Show panel", on_show, default=True),
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
    return icon


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
