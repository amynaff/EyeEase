"""
tray.py — a small icon in the menu bar (Mac) / system tray (Windows) that
shows/hides the control panel, matching how RedShift and EyeEase both live
in the tray rather than the dock/taskbar.
"""

import os
import sys

from PIL import Image, ImageDraw
import pystray


def _assets_dir():
    # PyInstaller unpacks bundled data next to sys._MEIPASS at runtime;
    # when running from source it's just the folder next to this file.
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets")


def make_icon_image():
    """Loads the app's icon.png; falls back to a plain circle if missing."""
    icon_path = os.path.join(_assets_dir(), "icon.png")
    if os.path.exists(icon_path):
        return Image.open(icon_path)

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=(255, 90, 54, 255))
    return img


def run_tray(app):
    """app is the EyeEaseApp instance (a customtkinter window)."""

    def on_show(icon, item):
        app.after(0, app.deiconify)

    def on_quit(icon, item):
        icon.stop()
        app.after(0, app.on_close)

    icon = pystray.Icon(
        "eyeease",
        make_icon_image(),
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
    return icon
