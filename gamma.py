"""
gamma.py — talks to the OS to change what color comes out of the screen.

Every pixel the GPU sends to the display passes through a "gamma ramp":
256 brightness levels for each of red, green, and blue. Normally these
ramps are a straight line (input 100 -> output 100). We bend the green
and blue lines downward, so no matter what color a pixel is supposed to
be, less green/blue light actually reaches your eyes.

warmth: 0.0 (screen unchanged) -> 1.0 (green and blue fully removed, pure red)
brightness: 0.15 -> 1.0 (scales all three channels down together, a software dim)
"""

import sys
import ctypes
import platform

RAMP_SIZE = 256


def build_ramp(warmth: float, brightness: float):
    """Returns three lists of 256 ints (0-65535) for R, G, B."""
    warmth = max(0.0, min(1.0, warmth))
    brightness = max(0.15, min(1.0, brightness))

    red, green, blue = [], [], []
    for i in range(RAMP_SIZE):
        base = i / (RAMP_SIZE - 1)  # 0.0 -> 1.0

        r = base
        g = base * (1 - warmth)          # green fades out as warmth rises
        b = base * (1 - warmth * 1.0)    # blue fades out first / fastest

        # brightness is a simple multiply — a "software dim" that doesn't
        # touch the physical backlight (that's the harder PWM-safe feature,
        # see README for why it's left out of this version)
        r *= brightness
        g *= brightness
        b *= brightness

        red.append(int(r * 65535))
        green.append(int(g * 65535))
        blue.append(int(b * 65535))

    return red, green, blue


class GammaController:
    """Applies a ramp to the display. Platform-specific under the hood."""

    def __init__(self):
        self.system = platform.system()  # 'Darwin', 'Windows', 'Linux'

    def apply(self, warmth: float, brightness: float):
        red, green, blue = build_ramp(warmth, brightness)
        if self.system == "Darwin":
            self._apply_macos(red, green, blue)
        elif self.system == "Windows":
            self._apply_windows(red, green, blue)
        else:
            raise RuntimeError(f"Unsupported platform: {self.system}")

    def reset(self):
        """Restore a normal, unmodified screen."""
        self.apply(warmth=0.0, brightness=1.0)

    # -- macOS ---------------------------------------------------------
    def _apply_macos(self, red, green, blue):
        # CoreGraphics: CGSetDisplayTransferByTable takes float arrays (0.0-1.0)
        cg = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        FloatArray = ctypes.c_float * RAMP_SIZE
        r = FloatArray(*[v / 65535 for v in red])
        g = FloatArray(*[v / 65535 for v in green])
        b = FloatArray(*[v / 65535 for v in blue])

        main_display = cg.CGMainDisplayID()
        cg.CGSetDisplayTransferByTable(
            main_display, RAMP_SIZE, r, g, b
        )
        # NOTE: for multi-monitor support, loop over CGGetActiveDisplayList()
        # and call CGSetDisplayTransferByTable for each display id — left as
        # a next step, see README.

    # -- Windows ---------------------------------------------------------
    def _apply_windows(self, red, green, blue):
        # GDI: SetDeviceGammaRamp wants a single WORD[3][256] buffer
        WORD = ctypes.c_ushort
        RampType = (WORD * RAMP_SIZE) * 3
        ramp = RampType()
        for i in range(RAMP_SIZE):
            ramp[0][i] = red[i]
            ramp[1][i] = green[i]
            ramp[2][i] = blue[i]

        hdc = ctypes.windll.user32.GetDC(0)
        ctypes.windll.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
        ctypes.windll.user32.ReleaseDC(0, hdc)
        # NOTE: for multi-monitor support, call EnumDisplayMonitors and get a
        # device context per monitor instead of the single GetDC(0) — RedShift
        # already does this, worth porting over as a next step.
