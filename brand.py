"""
brand.py — the one place the EyeEase palette and eye mark are defined.

Everything visual pulls from here: the panel, the tray icon, and the icon
generator. Keeping it in one module is what stops the app ending up with
three slightly different oranges that all claim to be the brand colour.

The accent IS what the product does — it is never picked, only derived.
LENS is exactly kelvin_to_hex(1200): the colour this app turns a screen at
its warmest, the zero-blue end. It is also, not by coincidence, the
red-orange of blue-blocker lenses, which is the thing people already
recognise this category by.

This used to be kelvin_to_hex(2700), the Evening preset, on the argument
that a red accent on a tool for removing harsh light argues with itself.
Two things were wrong with that. It isn't an alarm red, it's a lens; and
2700K stopped being the centre of the product once zero-blue became the
headline feature. Same rule, better reference point.

The accent also has to survive the app's own effect. Everything on screen,
including this panel, is filtered through the gamma ramp, and deep warmth
takes the blue channel to zero — so a blue or teal accent would darken to an
unreadable smudge exactly when the app is working hardest. Warm hues are the
only ones that stay legible at 1900K.

What the move costs, stated plainly: LENS is darker than the old amber, so
the ceiling for text on it drops from 10.92:1 to 6.58:1 and the 7.9:1 this
file used to hold itself to is simply unreachable. INK sits as close to that
ceiling as a hue-consistent colour gets. What it buys: the white eye in the
icon goes from 1.92:1 against the disc — under the 3:1 WCAG asks for
graphics, i.e. failing — to 3.19:1, passing.
"""

from PIL import Image, ImageChops, ImageDraw

# -- palette ------------------------------------------------------------
LENS = "#ff5600"         # primary accent — kelvin_to_hex(1200)
LENS_BRIGHT = "#ff8c52"   # hover / lifted state
LENS_DIM = "#8a2e00"      # active-but-quiet: preset chips, dimmed status dot
INK = "#170700"           # text and marks sitting on top of the lens (6.2:1)

# -- the off state ------------------------------------------------------
# BLUE is derived the same way LENS is, from the same temperature. LENS is
# the light 1200K lets *through*; BLUE is the light it takes *away* —
# (1,1,1) minus the 1200K multipliers, which lands on hue 200 degrees, and
# is the literal answer to "what is this app removing". Its lightness is
# then tuned until its luminance matches LENS's, so the two states weigh the
# same in a menu bar: 0.2817 against 0.2792.
#
# The warning at the top of this file — that a blue accent dies once the
# gamma ramp takes blue to zero — doesn't apply here, and that's the whole
# reason this colour can exist. Blue is the *off* state, and off means the
# ramp has been reset. This colour is only ever drawn on an untouched screen.
BLUE = "#0098e6"          # off / unfiltered — the light being let through
BLUE_BRIGHT = "#0aacff"   # hover / lifted state
BLUE_INK = "#00111a"      # text and marks sitting on top of blue (6.1:1)

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
    draws it live in two colours — the lens colour while the app is easing
    the screen, blue while it isn't — and a mark that's generated in one
    file and drawn in another is a mark that drifts.
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
