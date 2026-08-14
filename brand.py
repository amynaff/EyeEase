"""
brand.py — the one place the EyeEase palette and eye mark are defined.

Everything visual pulls from here: the panel, the tray icon, and the icon
generator. Keeping it in one module is what stops the app ending up with
three slightly different oranges that all claim to be the brand colour.

Why amber rather than a red: the accent IS what the product does. AMBER is
exactly kelvin_to_hex(2700) — the colour this app turns a screen at the
Evening preset, the setting most people leave it on. A red alarm accent on a
tool whose entire job is removing harsh light argues with itself.

The accent also has to survive the app's own effect. Everything on screen,
including this panel, is filtered through the gamma ramp, and deep warmth
takes the blue channel to zero — so a blue or teal accent would darken to an
unreadable smudge exactly when the app is working hardest. Warm hues are the
only ones that stay legible at 1900K.

The darker shades are derived from AMBER by lightness, then pushed further
until the text on them clears 4.5:1. The obvious arithmetic shades landed at
4.2 and 3.7, which look fine on a bright monitor and fail on a dim one.
"""

from PIL import Image, ImageChops, ImageDraw

# -- palette ------------------------------------------------------------
AMBER = "#ffa759"        # primary accent — kelvin_to_hex(2700)
AMBER_BRIGHT = "#fec28c"  # hover / lifted state
AMBER_DIM = "#a04b00"     # active-but-quiet: preset chips, dimmed status dot
INK = "#3f1d00"           # text and marks sitting on top of amber (7.9:1)

# -- the off state ------------------------------------------------------
# BLUE is derived the same way AMBER is, from the same two temperatures.
# AMBER is the light the Evening preset lets *through* (kelvin_to_hex(2700));
# BLUE is the light it takes *away* — (1,1,1) minus the 2700K multipliers,
# which lands on hue 208 degrees, and is the literal answer to "what is this
# app removing". Its lightness is then tuned until its luminance matches
# AMBER's, so the two states weigh the same in a menu bar: white-on-colour
# 1.93 vs 1.92, and against a dark menu bar 8.83 vs 8.85.
#
# The warning at the top of this file — that a blue accent dies once the
# gamma ramp takes blue to zero — doesn't apply here, and that's the whole
# reason this colour can exist. Blue is the *off* state, and off means the
# ramp has been reset. This colour is only ever drawn on an untouched screen.
BLUE = "#7ac1ff"          # off / unfiltered — the light being let through
BLUE_BRIGHT = "#a9d6ff"   # hover / lifted state
BLUE_INK = "#0a2942"      # text and marks sitting on top of blue (7.7:1)

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


def disc_icon(size: int, disc_color: str):
    """The round app/tray icon: a filled disc with the eye punched into it.

    Lives here rather than in the icon generator because the tray icon now
    draws it live in two colours — amber while the app is easing the screen,
    blue while it isn't — and a mark that's generated in one file and drawn
    in another is a mark that drifts.
    """
    disc = hex_to_rgba(disc_color)
    white = (255, 255, 255, 255)

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = size * 0.06
    draw.ellipse((margin, margin, size - margin, size - margin), fill=disc)

    img.paste(Image.new("RGBA", (size, size), white), (0, 0), eye_lens_mask(size))

    centre = size / 2
    iris_r = size * 0.11
    draw.ellipse(
        (centre - iris_r, centre - iris_r, centre + iris_r, centre + iris_r),
        fill=disc,
    )
    pupil_r = size * 0.05
    draw.ellipse(
        (centre - pupil_r, centre - pupil_r, centre + pupil_r, centre + pupil_r),
        fill=white,
    )
    return img
