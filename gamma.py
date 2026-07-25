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
import subprocess

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
        self._saved_hw_brightness = None  # set while PWM-safe mode is active

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

    # -- PWM-safe mode ---------------------------------------------------
    # The "brightness" slider above only ever dims via the gamma ramp — it
    # never touches the physical backlight. But the OS's own brightness
    # keys/slider do, and most laptop backlights use PWM (rapid on/off
    # flicker) to dim below 100%, which is what causes eye strain for
    # PWM-sensitive people. PWM-safe mode locks the physical backlight to
    # 100% (flicker-free) so all dimming happens in the gamma ramp instead.
    #
    # Only the built-in/primary display is supported. External monitors
    # need DDC/CI, which has no built-in OS API on either platform (RedShift
    # doesn't support it either) — left as a future step.

    def enable_pwm_safe(self):
        """Locks the physical backlight to 100%, remembering the old level
        so it can be restored later. Returns True on success."""
        current = self._get_hw_brightness()
        if current is None:
            return False
        self._saved_hw_brightness = current
        return self._set_hw_brightness(1.0)

    def disable_pwm_safe(self):
        """Restores the physical backlight to whatever it was before
        enable_pwm_safe() was called."""
        if self._saved_hw_brightness is not None:
            self._set_hw_brightness(self._saved_hw_brightness)
            self._saved_hw_brightness = None

    def _get_hw_brightness(self):
        try:
            if self.system == "Darwin":
                return self._get_hw_brightness_macos()
            elif self.system == "Windows":
                return self._get_hw_brightness_windows()
        except Exception:
            pass
        return None

    def _set_hw_brightness(self, level: float) -> bool:
        try:
            if self.system == "Darwin":
                return self._set_hw_brightness_macos(level)
            elif self.system == "Windows":
                return self._set_hw_brightness_windows(level)
        except Exception:
            pass
        return False

    # CoreDisplay is a private framework, but it's the same one the popular
    # `brightness` CLI and several menu-bar apps use to reach the built-in
    # panel on both Intel and Apple Silicon Macs (IOKit's public API stopped
    # working for internal displays on Apple Silicon).
    def _core_display(self):
        return ctypes.CDLL(
            "/System/Library/PrivateFrameworks/CoreDisplay.framework/CoreDisplay"
        )

    def _main_display_id(self):
        cg = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        return cg.CGMainDisplayID()

    def _get_hw_brightness_macos(self):
        core_display = self._core_display()
        display_id = self._main_display_id()
        core_display.CoreDisplay_Display_GetUserBrightness.restype = ctypes.c_double
        value = core_display.CoreDisplay_Display_GetUserBrightness(display_id)
        return float(value)

    def _set_hw_brightness_macos(self, level: float) -> bool:
        core_display = self._core_display()
        display_id = self._main_display_id()
        core_display.CoreDisplay_Display_SetUserBrightness(
            display_id, ctypes.c_double(level)
        )
        return True

    # Windows exposes the internal laptop panel's brightness through WMI
    # (root\wmi, WmiMonitorBrightness / WmiMonitorBrightnessMethods) rather
    # than a plain Win32 call. Shelling out to PowerShell avoids adding a
    # WMI client dependency just for this.
    # Get-WmiObject throwing inside -Command doesn't reliably surface as a
    # non-zero process exit code, so both calls below wrap the WMI access in
    # an explicit try/catch and print a sentinel — the only way to tell a
    # monitor with no WmiMonitorBrightness* support (most external/desktop
    # monitors) apart from a real success.
    def _get_hw_brightness_windows(self):
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "try { "
                "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness "
                "-ErrorAction Stop).CurrentBrightness "
                "} catch { Write-Output 'FAIL' }",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout.strip()
        if output == "FAIL" or not output:
            return None
        return int(output) / 100.0

    def _set_hw_brightness_windows(self, level: float) -> bool:
        percent = max(0, min(100, round(level * 100)))
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "try { "
                "(Get-WmiObject -Namespace root/wmi "
                "-Class WmiMonitorBrightnessMethods -ErrorAction Stop)."
                f"WmiSetBrightness(1, {percent}) | Out-Null; "
                "Write-Output 'OK' "
                "} catch { Write-Output 'FAIL' }",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() == "OK"

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
