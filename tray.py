"""
tray.py — a small icon in the menu bar (Mac) / system tray (Windows) that
shows/hides the control panel, matching how RedShift and Tap Zap both live
in the tray rather than the dock/taskbar.
"""

from PIL import Image, ImageDraw
import pystray


def make_icon_image():
    """Draws a simple orange circle — swap this for a real .png/.ico later."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=(255, 90, 54, 255))
    return img


def run_tray(app):
    """app is the TapZapLiteApp instance (a customtkinter window)."""

    def on_show(icon, item):
        app.after(0, app.deiconify)

    def on_quit(icon, item):
        icon.stop()
        app.after(0, app.on_close)

    icon = pystray.Icon(
        "tapzaplite",
        make_icon_image(),
        "Tap Zap Lite",
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
