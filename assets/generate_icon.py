"""
generate_icon.py — builds the app icon from scratch with Pillow (no binary
asset checked in) and converts it to .icns (macOS) and .ico (Windows).

Run once from the repo root: `python3 assets/generate_icon.py`
Regenerate only if the design changes; the outputs (icon.png/.icns/.ico)
are committed so packaging doesn't depend on re-running this.
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).parent
SIZE = 1024

# Same orange as the zap button in app_ui.py, so the app icon, tray icon,
# and in-app button all read as the same brand.
ORANGE = (255, 90, 54, 255)
WHITE = (255, 255, 255, 255)


def build_icon() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = SIZE * 0.06
    draw.ellipse((margin, margin, SIZE - margin, SIZE - margin), fill=ORANGE)

    # A simple lightning-bolt polygon, centered, matching the ⚡ used on the
    # in-app zap button.
    bolt = [
        (0.58, 0.12), (0.34, 0.56), (0.48, 0.56),
        (0.42, 0.90), (0.68, 0.44), (0.53, 0.44),
    ]
    points = [(x * SIZE, y * SIZE) for x, y in bolt]
    draw.polygon(points, fill=WHITE)

    return img


def save_png(img: Image.Image):
    path = ASSETS / "icon.png"
    img.save(path)
    return path


def save_ico(img: Image.Image):
    path = ASSETS / "icon.ico"
    sizes = [(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)]
    img.save(path, format="ICO", sizes=sizes)
    return path


def save_icns(img: Image.Image, png_path: Path):
    path = ASSETS / "icon.icns"
    if sys.platform != "darwin":
        print("Skipping .icns (needs macOS's iconutil) — build that on a Mac.")
        return None

    iconset = ASSETS / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    # iconutil wants this exact filename/size matrix, including the 2x
    # ("@2x") variants for Retina.
    specs = [
        ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
    ]
    for name, size in specs:
        img.resize((size, size), Image.LANCZOS).save(iconset / name)

    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(path)],
        check=True,
    )
    for f in iconset.iterdir():
        f.unlink()
    iconset.rmdir()
    return path


if __name__ == "__main__":
    icon = build_icon()
    png_path = save_png(icon)
    print(f"wrote {png_path}")
    ico_path = save_ico(icon)
    print(f"wrote {ico_path}")
    icns_path = save_icns(icon, png_path)
    if icns_path:
        print(f"wrote {icns_path}")
