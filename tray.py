"""
tray.py — a small icon in the menu bar (Mac) / system tray (Windows) that
shows/hides the control panel, matching how RedShift and EyeEase both live
in the tray rather than the dock/taskbar.
"""

import pystray

from brand import AMBER, BLUE, disc_icon

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
    return disc_icon(TRAY_ICON_SIZE, AMBER if is_on else BLUE)


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
    return icon
