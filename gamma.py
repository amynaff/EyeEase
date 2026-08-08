"""
gamma.py — talks to the OS to change what color comes out of the screen.

Every pixel the GPU sends to the display passes through a "gamma ramp":
256 brightness levels for each of red, green, and blue. Normally these
ramps are a straight line (input 100 -> output 100). We bend the green
and blue lines downward, so no matter what color a pixel is supposed to
be, less green/blue light actually reaches your eyes.

How far we bend them is set by a colour temperature in Kelvin — the same
scale f.lux and Redshift use, so the numbers mean something to people who
have used those:

    6500K  daylight; screen left exactly as-is
    5000K  barely-there warm cast, fine for daytime
    4000K  soft white, comfortable for reading
    2700K  incandescent bulb, the usual evening setting
    1900K  candlelight, almost no blue left
    1200K  deep amber, the most aggressive setting

Warmth is NOT "turn green and blue down together" — doing that just
desaturates the picture toward red and looks like a darkroom. A genuinely
warm screen follows the blackbody curve, where blue falls away fast while
green falls much more slowly. That gap between the two curves is the whole
reason 2700K reads as candlelight instead of red. kelvin_to_rgb() computes
it.

brightness: 0.15 -> 1.0 (scales all three channels together, a software dim)
"""

import sys
import math
import ctypes
import platform
import subprocess

RAMP_SIZE = 256

# Usable ends of the colour-temperature slider. 6500K is the neutral point
# (ramp left as a straight line, screen untouched); 1200K matches the
# warmest setting f.lux offers.
KELVIN_NEUTRAL = 6500
KELVIN_MIN = 1200
KELVIN_MAX = 6500

# How far PWM-safe mode nudges the backlight when testing whether it can
# drive it at all. Big enough to read back reliably, small enough that the
# momentary blip isn't worth noticing.
PWM_PROBE_DELTA = 0.05


def _planckian(kelvin: float):
    """Raw 0-255 channel values for a blackbody radiator at `kelvin`.

    Tanner Helland's well-known piecewise approximation of the Planckian
    locus. Accurate to about 1% across 1000-40000K, which is far tighter
    than the eye can resolve as a colour cast.
    """
    kelvin = max(1000.0, min(40000.0, float(kelvin)))
    t = kelvin / 100.0

    if t <= 66:
        red = 255.0
        green = 99.4708025861 * math.log(t) - 161.1195681661
    else:
        red = 329.698727446 * ((t - 60) ** -0.1332047592)
        green = 288.1221695283 * ((t - 60) ** -0.0755148492)

    if t >= 66:
        blue = 255.0
    elif t <= 19:
        # Below ~1900K a blackbody emits essentially no blue at all. The
        # curve below approaches zero smoothly as t nears 19, so this is a
        # floor rather than a cliff.
        blue = 0.0
    else:
        blue = 138.5177312231 * math.log(t - 10) - 305.0447927307

    return (
        max(0.0, min(255.0, red)),
        max(0.0, min(255.0, green)),
        max(0.0, min(255.0, blue)),
    )


def kelvin_to_rgb(kelvin: float):
    """Colour temperature -> (r, g, b) channel multipliers, each 0.0-1.0.

    Normalised against the 6500K result so that kelvin=6500 returns exactly
    (1.0, 1.0, 1.0) — a screen we haven't touched. Without that step even
    the "neutral" setting would tint slightly, since the raw curve doesn't
    hit pure white at any temperature.
    """
    r, g, b = _planckian(kelvin)
    nr, ng, nb = _planckian(KELVIN_NEUTRAL)
    return (r / nr, g / ng, b / nb)


def kelvin_to_hex(kelvin: float, brightness: float = 1.0) -> str:
    """The tint as a '#rrggbb' string, for showing a preview swatch in the UI.

    This is the colour a white pixel ends up as, so the swatch shows the
    user what their screen is actually about to do.
    """
    r, g, b = kelvin_to_rgb(kelvin)
    scale = max(0.15, min(1.0, brightness))
    return "#{:02x}{:02x}{:02x}".format(
        int(round(r * scale * 255)),
        int(round(g * scale * 255)),
        int(round(b * scale * 255)),
    )


def build_ramp(kelvin: float, brightness: float):
    """Returns three lists of 256 ints (0-65535) for R, G, B."""
    kelvin = max(KELVIN_MIN, min(KELVIN_MAX, kelvin))
    brightness = max(0.15, min(1.0, brightness))

    kr, kg, kb = kelvin_to_rgb(kelvin)

    red, green, blue = [], [], []
    for i in range(RAMP_SIZE):
        base = i / (RAMP_SIZE - 1)  # 0.0 -> 1.0

        # brightness is a simple multiply — a "software dim" that never
        # touches the physical backlight. PWM-safe mode below is what pins
        # the backlight at 100% so it can't flicker while we dim here.
        r = base * kr * brightness
        g = base * kg * brightness
        b = base * kb * brightness

        red.append(int(round(r * 65535)))
        green.append(int(round(g * 65535)))
        blue.append(int(round(b * 65535)))

    return red, green, blue


class GammaController:
    """Applies a ramp to the display. Platform-specific under the hood."""

    def __init__(self):
        self.system = platform.system()  # 'Darwin', 'Windows', 'Linux'
        self._saved_hw_brightness = None  # set while PWM-safe mode is active

    def apply(self, kelvin: float, brightness: float) -> bool:
        """Push a ramp to the display. Returns False if the OS refused it.

        Both platforms report failure through a return value rather than an
        exception, and both were previously discarded — so a rejected ramp
        was indistinguishable from a successful one, and the screen just
        never changed.
        """
        red, green, blue = build_ramp(kelvin, brightness)
        if self.system == "Darwin":
            return self._apply_macos(red, green, blue)
        if self.system == "Windows":
            return self._apply_windows(red, green, blue)
        raise RuntimeError(f"Unsupported platform: {self.system}")

    def reset(self) -> bool:
        """Restore a normal, unmodified screen."""
        return self.apply(kelvin=KELVIN_NEUTRAL, brightness=1.0)

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

    def _backlight_is_writable(self, current: float) -> bool:
        """Prove we can actually move the backlight, instead of assuming.

        The macOS write call reports success (raises nothing, returns True)
        while silently doing nothing whenever the process isn't allowed to
        drive CoreDisplay — and on some macOS versions it does nothing at
        all. There is no error to catch, so the only honest test is to move
        the brightness and read it back.

        This matters most when the backlight already sits at 100%: setting
        it to 100% again "succeeds" trivially, which is how a completely
        dead write path used to pass for a working PWM-safe mode. So the
        probe deliberately aims somewhere the backlight isn't.
        """
        probe = current - PWM_PROBE_DELTA
        if probe < 0.1:
            probe = current + PWM_PROBE_DELTA
        if probe > 1.0 or probe < 0.0:
            return False

        self._set_hw_brightness(probe)
        seen = self._get_hw_brightness()

        # Ask "did it move?", not "did it land exactly on the probe?".
        # Windows exposes only the discrete brightness levels a panel
        # actually supports, so a 5% request can settle on the nearest
        # supported step instead of the exact value — and demanding an exact
        # match would report a perfectly controllable display as
        # uncontrollable.
        moved = seen is not None and abs(seen - current) >= PWM_PROBE_DELTA / 2

        # Put it back whatever the answer — the probe is a test, not a change.
        self._set_hw_brightness(current)
        return moved

    def can_control_backlight(self) -> bool:
        """Whether no-flicker dimming is possible here at all.

        Lets the UI leave the option out entirely rather than showing a
        switch that can only ever refuse. Costs one probe: on a machine that
        does respond, the backlight blips 5% for a few milliseconds; on one
        that doesn't — the case this exists to detect — nothing moves.
        """
        current = self._get_hw_brightness()
        if current is None:
            return False
        return self._backlight_is_writable(current)

    def enable_pwm_safe(self):
        """Locks the physical backlight to 100%, remembering the old level
        so it can be restored later. Returns True only if the lock is
        verifiably in place."""
        current = self._get_hw_brightness()
        if current is None:
            return False

        if not self._backlight_is_writable(current):
            return False

        self._saved_hw_brightness = current
        self._set_hw_brightness(1.0)

        # Confirm unconditionally. The old code only checked when the
        # backlight started below 98%, so a display already at full let an
        # entirely non-functional write path report success.
        after = self._get_hw_brightness()
        if after is None or after < 0.98:
            self._set_hw_brightness(current)
            self._saved_hw_brightness = None
            return False
        return True

    def hold_pwm_safe(self) -> bool:
        """Re-assert the 100% lock; call this periodically while active.

        Without it, "locked to 100%" is only true for the instant the switch
        is flipped — pressing the brightness keys, or macOS auto-brightness,
        drops the backlight straight back into PWM dimming while the UI
        still claims the mode is on.

        Returns False if the backlight has slipped and can't be put back,
        which is the caller's cue to stop claiming the mode is active.
        """
        if self._saved_hw_brightness is None:
            return True  # not active, nothing to hold

        current = self._get_hw_brightness()
        if current is None:
            return False
        if current >= 0.98:
            return True  # still where we left it

        self._set_hw_brightness(1.0)
        after = self._get_hw_brightness()
        return after is not None and after >= 0.98

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
        # CoreDisplay was promoted from PrivateFrameworks to Frameworks at
        # some point (confirmed present as a public framework on macOS
        # 26.5.2) — try both, oldest path last so newer systems resolve
        # fastest.
        for path in (
            "/System/Library/Frameworks/CoreDisplay.framework/CoreDisplay",
            "/System/Library/PrivateFrameworks/CoreDisplay.framework/CoreDisplay",
        ):
            try:
                return ctypes.CDLL(path)
            except OSError:
                continue
        raise OSError("CoreDisplay framework not found")

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
    def _apply_macos(self, red, green, blue) -> bool:
        # CoreGraphics: CGSetDisplayTransferByTable takes float arrays (0.0-1.0)
        cg = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        FloatArray = ctypes.c_float * RAMP_SIZE
        r = FloatArray(*[v / 65535 for v in red])
        g = FloatArray(*[v / 65535 for v in green])
        b = FloatArray(*[v / 65535 for v in blue])

        main_display = cg.CGMainDisplayID()
        # Returns a CGError; 0 is success. Checked for the same reason as the
        # Windows call — a refusal here is otherwise silent.
        return cg.CGSetDisplayTransferByTable(
            main_display, RAMP_SIZE, r, g, b
        ) == 0
        # NOTE: for multi-monitor support, loop over CGGetActiveDisplayList()
        # and call CGSetDisplayTransferByTable for each display id — left as
        # a next step, see README.

    # -- Windows ---------------------------------------------------------
    def _apply_windows(self, red, green, blue) -> bool:
        # GDI: SetDeviceGammaRamp wants a single WORD[3][256] buffer
        WORD = ctypes.c_ushort
        RampType = (WORD * RAMP_SIZE) * 3
        ramp = RampType()
        for i in range(RAMP_SIZE):
            ramp[0][i] = red[i]
            ramp[1][i] = green[i]
            ramp[2][i] = blue[i]

        hdc = ctypes.windll.user32.GetDC(0)
        if not hdc:
            return False
        try:
            # This return value matters. Windows sanity-checks gamma ramps and
            # refuses ones it considers too far from linear — the deepest
            # settings here drive blue to zero across the whole ramp, which is
            # exactly the shape it objects to. Ignoring the result meant a
            # refusal looked identical to success: no error, no exception, and
            # a screen that simply never changed.
            #
            # The documented escape hatch is a machine-wide registry value,
            # HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ICM
            # \GdiIcmGammaRange = 256 (Redshift and f.lux both rely on it).
            # This app does not write it — that's a system-wide change and the
            # user's call — so the UI reports the refusal instead.
            applied = bool(ctypes.windll.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp)))
        finally:
            ctypes.windll.user32.ReleaseDC(0, hdc)
        return applied
        # NOTE: for multi-monitor support, call EnumDisplayMonitors and get a
        # device context per monitor instead of the single GetDC(0) — RedShift
        # already does this, worth porting over as a next step.
