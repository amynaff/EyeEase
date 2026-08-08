"""
brand.py — the one place the EyeEase palette and eye mark are defined.

Everything visual pulls from here: the panel, the tray icon, and the icon
generator. Keeping it in one module is what stops the app ending up with
three slightly different oranges that all claim to be the brand colour.

Why amber rather than a red: amber is the colour the app itself produces at
evening temperatures — kelvin_to_hex(2700) is #ffa759 — so the brand matches
what the product actually does to a screen. A red alarm accent on a tool
whose entire job is removing harsh light argues with itself.
"""

from PIL import Image, ImageChops, ImageDraw

# -- palette ------------------------------------------------------------
AMBER = "#f59e0b"        # primary accent
AMBER_BRIGHT = "#ffb733"  # hover / lifted state
AMBER_DIM = "#7a4f06"     # inactive or "off" state
INK = "#1a1200"           # text and marks sitting on top of amber

BG = "#0d0d0f"
SURFACE = "#17171b"
SURFACE_HI = "#232329"
TEXT = "#f2f2f4"
TEXT_MUTED = "#8a8a94"


def hex_to_rgba(value: str, alpha: int = 255):
    value = value.lstrip("#")
    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
        alpha,
    )


# -- the eye mark -------------------------------------------------------
# An almond lens: two big overlapping circles, kept only where they overlap.
# Defined once as a mask so the app icon and the in-panel button draw the
# exact same shape at completely different sizes.
#
# The circles are offset *vertically*, which makes the lens wide — offsetting
# them sideways instead produces a tall almond that reads as a leaf at large
# sizes and as a vertical sliver by the time it's a 16px tray icon.


def eye_lens_mask(size: int, lens_ratio: float = 0.42, offset_ratio: float = 0.27):
    """An 'L' mode mask of the almond eye outline, `size` x `size`."""
    centre = size / 2
    lens_r = size * lens_ratio
    offset = size * offset_ratio

    upper = Image.new("L", (size, size), 0)
    ImageDraw.Draw(upper).ellipse(
        (centre - lens_r, centre - offset - lens_r,
         centre + lens_r, centre - offset + lens_r),
        fill=255,
    )
    lower = Image.new("L", (size, size), 0)
    ImageDraw.Draw(lower).ellipse(
        (centre - lens_r, centre + offset - lens_r,
         centre + lens_r, centre + offset + lens_r),
        fill=255,
    )
    # Keep only where both circles are lit — the lens between them.
    return ImageChops.darker(upper, lower)


def eye_image(size: int, eye_color: str, iris_color: str):
    """A small transparent-background eye mark, for use as a button glyph.

    Drawn at 4x and downsampled, because the lens comes to a point at each
    corner and those points alias badly at button sizes otherwise.
    """
    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    lens = eye_lens_mask(big)
    img.paste(Image.new("RGBA", (big, big), hex_to_rgba(eye_color)), (0, 0), lens)

    # The iris is punched in the button's own colour, so the mark reads as an
    # eye rather than a solid blob once it's down at ~20px.
    #
    # The lens is only (lens_ratio - offset_ratio) = 0.15 of the size tall at
    # its centre, so an iris of that same radius punches clean through and
    # leaves nothing but the two corner points. Keep it comfortably under
    # half that.
    draw = ImageDraw.Draw(img)
    centre = big / 2
    iris_r = big * 0.06
    draw.ellipse(
        (centre - iris_r, centre - iris_r, centre + iris_r, centre + iris_r),
        fill=hex_to_rgba(iris_color),
    )

    return img.resize((size, size), Image.LANCZOS)
