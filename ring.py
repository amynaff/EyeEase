"""
ring.py — draws the day ring: 24 hours of what the screen is going to do.

Rendered with Pillow rather than Tk canvas arcs, because a canvas arc has
hard edges and this is 360 adjacent wedges whose whole point is that the
colour slides smoothly between them. Drawn at 2x and downsampled, which is
cheaper than it sounds and is the only reason the seams disappear.

The ring is a readout, never a control. Everything it shows is the product
of settings changed elsewhere in the panel — the temptation to make it
draggable is the temptation to make a clock face that lies about the time.
"""

from PIL import Image, ImageDraw

import brand
from gamma import kelvin_to_hex, KELVIN_MAX, KELVIN_MIN

SUPERSAMPLE = 2
SEGMENTS = 360  # one wedge per degree; 24h maps to four minutes each


def _intensity_to_kelvin(intensity: float) -> float:
    intensity = max(0.0, min(1.0, intensity))
    return KELVIN_MAX - intensity * (KELVIN_MAX - KELVIN_MIN)


def render(size, schedule, depth, now, auto, is_on):
    """A transparent-background donut, `size` x `size` points.

    depth is the night target as a slider position; the ring shows depth
    scaled by the schedule across the day, which is exactly what the screen
    will do. With auto off there's no curve to draw, so it becomes a single
    even band at the current setting rather than pretending to a day shape
    it isn't following.
    """
    px = int(size * SUPERSAMPLE)
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    outer = px / 2
    inner = outer * 0.68
    box = [0, 0, px - 1, px - 1]

    live = auto and schedule.is_usable() and is_on

    for seg in range(SEGMENTS):
        if live:
            minutes = (seg / SEGMENTS) * 24 * 60
            when = now.replace(hour=0, minute=0, second=0, microsecond=0)
            when += _minutes(minutes)
            fraction = schedule.night_fraction(when) * depth
        else:
            fraction = depth if is_on else 0.0

        if fraction <= 0.004:
            colour = brand.SURFACE_HI
        else:
            colour = kelvin_to_hex(_intensity_to_kelvin(fraction))

        # -90 puts midnight at the top, so the ring reads like a clock.
        start = seg * (360 / SEGMENTS) - 90
        d.pieslice(box, start, start + (360 / SEGMENTS) + 0.7,
                   fill=brand.hex_to_rgba(colour))

    # Where we are on the ring. Without it the ring is a picture of a day in
    # the abstract — you can see that the screen warms in the evening, but
    # not whether that has happened yet, which is the one thing you actually
    # came to find out.
    angle = ((now.hour * 60 + now.minute) / (24 * 60)) * 360.0 - 90
    d.pieslice(box, angle - 0.9, angle + 0.9, fill=brand.hex_to_rgba(brand.TEXT))

    # Punch the middle out last: drawing wedges over a hole leaves seams
    # where the antialiasing of each wedge meets the background.
    d.ellipse([outer - inner, outer - inner, outer + inner, outer + inner],
              fill=(0, 0, 0, 0))

    # Midnight tick, so the ring reads as a clock rather than a dial that
    # happens to be round. Drawn after the hole so it survives it.
    d.pieslice([outer - inner - 5 * SUPERSAMPLE, outer - inner - 5 * SUPERSAMPLE,
                outer + inner + 5 * SUPERSAMPLE, outer + inner + 5 * SUPERSAMPLE],
               -91.2, -88.8, fill=brand.hex_to_rgba(brand.TEXT_MUTED))
    d.ellipse([outer - inner, outer - inner, outer + inner, outer + inner],
              fill=(0, 0, 0, 0))

    return img.resize((int(size), int(size)), Image.LANCZOS)


def _minutes(count):
    from datetime import timedelta

    return timedelta(minutes=count)
