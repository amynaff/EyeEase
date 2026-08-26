"""test_gamma.py — the colour maths, pinned down.

These cover the pure functions in gamma.py: _planckian, kelvin_to_rgb,
kelvin_to_hex and build_ramp. Nothing here touches a display; the OS calls
in GammaController need real hardware and are listed as manual checks in
the README instead.

The point of testing this layer is that its failures are silent. A ramp
with a rounding error, an off-by-one at the top of the scale, or a blue
curve that creeps back up at the warm end doesn't crash and doesn't log —
the screen just looks slightly wrong, and nobody files a bug for slightly
wrong. Every assertion below is something that would otherwise only be
caught by someone noticing their screen looked off.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gamma import (  # noqa: E402
    KELVIN_MAX,
    KELVIN_MIN,
    KELVIN_NEUTRAL,
    RAMP_SIZE,
    _planckian,
    build_ramp,
    kelvin_to_hex,
    kelvin_to_rgb,
)

# The slider, sampled finely enough to catch a kink in a curve.
SLIDER = [KELVIN_MIN + i * 25 for i in range((KELVIN_MAX - KELVIN_MIN) // 25 + 1)]


class TestPlanckian(unittest.TestCase):
    """The blackbody approximation itself."""

    def test_channels_stay_in_range_across_the_whole_domain(self):
        # Well beyond the slider, because _planckian clamps its input and the
        # clamp is the thing being checked.
        for kelvin in [0, 500, 1000, 1200, 1900, 2700, 4000, 6500, 10000, 40000, 99999]:
            r, g, b = _planckian(kelvin)
            for name, value in (("red", r), ("green", g), ("blue", b)):
                self.assertGreaterEqual(value, 0.0, f"{name} negative at {kelvin}K")
                self.assertLessEqual(value, 255.0, f"{name} over 255 at {kelvin}K")

    def test_red_is_saturated_across_the_entire_slider(self):
        # Below ~6600K the red channel pins at 255. build_ramp relies on this:
        # it's why warming the screen never dims red, only bends green and blue.
        for kelvin in SLIDER:
            self.assertEqual(_planckian(kelvin)[0], 255.0, f"red not full at {kelvin}K")

    def test_blue_is_exactly_zero_at_and_below_the_documented_floor(self):
        for kelvin in [1000, 1200, 1500, 1900]:
            self.assertEqual(_planckian(kelvin)[2], 0.0, f"blue leaked at {kelvin}K")

    def test_no_discontinuity_at_the_1900K_blue_floor(self):
        # The docstring claims the curve "approaches zero smoothly as t nears
        # 19, so this is a floor rather than a cliff". If that stopped being
        # true there'd be a visible jump as the slider crossed 1900K.
        just_above = _planckian(1901)[2]
        self.assertLess(just_above, 1.0, "blue jumps at the 1900K floor")

    def test_the_formula_seam_sits_outside_the_usable_slider(self):
        # _planckian switches to entirely different formulas for red and green
        # at t > 66 (6600K), and Helland's piecewise fit has a small seam
        # there — green jumps by around 3 counts across it. That is harmless
        # only because KELVIN_MAX is 6500, so no slider position can reach it.
        # If the neutral end were ever raised past 6600K, this is the test that
        # should stop it.
        self.assertLess(KELVIN_MAX, 6600, "the slider now reaches the formula seam")

    def test_curves_are_continuous_across_the_whole_slider(self):
        # Within the range people can actually drag, adjacent temperatures must
        # not jump. A step here would feel like a detent in a slider that is
        # supposed to be smooth.
        step = 5
        previous = _planckian(KELVIN_MIN)
        for kelvin in range(KELVIN_MIN + step, KELVIN_MAX + 1, step):
            current = _planckian(kelvin)
            for name, before, after in zip("rgb", previous, current):
                self.assertLess(
                    abs(after - before), 2.0, f"{name} jumps near {kelvin}K"
                )
            previous = current


class TestKelvinToRgb(unittest.TestCase):
    """Normalised multipliers — the layer build_ramp actually consumes."""

    def test_neutral_is_exactly_untouched(self):
        # Not "close to" 1.0. If 6500K tinted even slightly, the app's claim
        # that the neutral end leaves the screen alone would be false, and the
        # auto schedule would sit on a faintly wrong screen all day.
        self.assertEqual(kelvin_to_rgb(KELVIN_NEUTRAL), (1.0, 1.0, 1.0))

    def test_multipliers_stay_within_unit_range(self):
        for kelvin in SLIDER:
            for name, value in zip("rgb", kelvin_to_rgb(kelvin)):
                self.assertGreaterEqual(value, 0.0, f"{name} negative at {kelvin}K")
                self.assertLessEqual(value, 1.0, f"{name} above 1.0 at {kelvin}K")

    def test_red_never_dims_anywhere_on_the_slider(self):
        for kelvin in SLIDER:
            self.assertEqual(kelvin_to_rgb(kelvin)[0], 1.0, f"red dimmed at {kelvin}K")

    def test_warmer_never_raises_green_or_blue(self):
        # Monotonicity is the invariant that makes the slider feel like a
        # slider. A non-monotonic curve would mean dragging further toward
        # "warmer" made the screen cooler somewhere in the middle.
        previous_g, previous_b = 0.0, 0.0
        for kelvin in SLIDER:  # ascending: 1200K -> 6500K
            _, g, b = kelvin_to_rgb(kelvin)
            self.assertGreaterEqual(g, previous_g - 1e-9, f"green dips at {kelvin}K")
            self.assertGreaterEqual(b, previous_b - 1e-9, f"blue dips at {kelvin}K")
            previous_g, previous_b = g, b

    def test_blue_falls_faster_than_green(self):
        # The README's central claim: warmth is the *gap* between the green and
        # blue curves, and closing that gap would turn the evening setting from
        # candlelight into a red darkroom.
        for kelvin in [2000, 2700, 3500, 4000, 5000]:
            _, g, b = kelvin_to_rgb(kelvin)
            self.assertLess(b, g, f"blue not below green at {kelvin}K")
        _, g, b = kelvin_to_rgb(2700)
        self.assertLess(b, g * 0.75, "the 2700K green/blue gap has collapsed")

    def test_clamps_beyond_the_slider_ends(self):
        self.assertEqual(kelvin_to_rgb(-5000), kelvin_to_rgb(1000))
        self.assertEqual(kelvin_to_rgb(99999), kelvin_to_rgb(40000))


class TestBuildRamp(unittest.TestCase):
    """The 256-entry tables handed to the OS."""

    def _all_channels(self, *args, **kwargs):
        return zip("rgb", build_ramp(*args, **kwargs))

    def test_shape(self):
        for name, channel in self._all_channels(2700, 1.0):
            self.assertEqual(len(channel), RAMP_SIZE, f"{name} wrong length")
            for value in channel:
                self.assertIsInstance(value, int, f"{name} has a non-int entry")

    def test_neutral_full_brightness_is_the_identity_ramp(self):
        # 65535 / 255 is exactly 257, so an untouched ramp has an exact
        # closed form. Any rounding drift shows up here as an off-by-one.
        red, green, blue = build_ramp(KELVIN_NEUTRAL, 1.0)
        expected = [i * 257 for i in range(RAMP_SIZE)]
        self.assertEqual(red, expected)
        self.assertEqual(green, expected)
        self.assertEqual(blue, expected)

    def test_entries_stay_inside_16_bit_range(self):
        # These become c_ushort on both platforms. An out-of-range value is a
        # ctypes overflow at the boundary, not a wrong colour.
        for kelvin in SLIDER:
            for brightness in (0.15, 0.5, 1.0):
                for name, channel in self._all_channels(kelvin, brightness):
                    self.assertGreaterEqual(min(channel), 0, f"{name} negative")
                    self.assertLessEqual(
                        max(channel), 65535, f"{name} over 16 bits at {kelvin}K"
                    )

    def test_black_stays_black(self):
        for kelvin in SLIDER:
            for brightness in (0.15, 0.5, 1.0):
                for name, channel in self._all_channels(kelvin, brightness):
                    self.assertEqual(channel[0], 0, f"{name} lifts black at {kelvin}K")

    def test_every_ramp_is_monotonic(self):
        # A ramp that dips would posterise: two different input levels mapping
        # to the same or inverted output, visible as banding in gradients.
        for kelvin in SLIDER:
            for brightness in (0.15, 0.4, 1.0):
                for name, channel in self._all_channels(kelvin, brightness):
                    for i in range(1, RAMP_SIZE):
                        self.assertGreaterEqual(
                            channel[i],
                            channel[i - 1],
                            f"{name} dips at index {i} ({kelvin}K, {brightness})",
                        )

    def test_brightness_scales_channels_together(self):
        # Brightness is a dim, not a tint: halving it must not shift the colour.
        full_r, full_g, full_b = build_ramp(2700, 1.0)
        half_r, half_g, half_b = build_ramp(2700, 0.5)
        top = RAMP_SIZE - 1
        for name, full, half in (
            ("red", full_r, half_r),
            ("green", full_g, half_g),
            ("blue", full_b, half_b),
        ):
            self.assertAlmostEqual(
                half[top] / full[top], 0.5, places=3, msg=f"{name} scaled unevenly"
            )

    def test_clamps_out_of_range_arguments(self):
        self.assertEqual(build_ramp(500, 1.0), build_ramp(KELVIN_MIN, 1.0))
        self.assertEqual(build_ramp(99999, 1.0), build_ramp(KELVIN_MAX, 1.0))
        self.assertEqual(build_ramp(2700, -1.0), build_ramp(2700, 0.15))
        self.assertEqual(build_ramp(2700, 5.0), build_ramp(2700, 1.0))


class TestZeroBlue(unittest.TestCase):
    """The switch that promises literal zeros."""

    def test_blue_is_every_entry_zero(self):
        # "Nothing here depends on where a curve happens to land, and no later
        # rounding can put a count of blue back" — the whole promise of the
        # switch, so it's asserted on all 256 entries rather than a sample.
        for brightness in (0.15, 0.5, 1.0):
            _, _, blue = build_ramp(KELVIN_NEUTRAL, brightness, zero_blue=True)
            self.assertEqual(set(blue), {0}, f"blue survived at brightness {brightness}")

    def test_blue_is_zeroed_defensively_not_just_because_the_curve_says_so(self):
        # At KELVIN_MIN the blackbody curve already returns blue = 0, so simply
        # deleting the explicit `kb = 0.0` in build_ramp leaves every other
        # assertion in this file passing. That makes the guard invisible to
        # tests exactly where it matters most — it exists so the promise holds
        # even if the curve, the pinned temperature, or the rounding changes.
        #
        # So: feed build_ramp a curve that does return blue, and require zeros
        # anyway. This is the only test here that fails if the guard is removed.
        leaky = lambda kelvin: (1.0, 1.0, 1.0)  # noqa: E731
        with mock.patch("gamma.kelvin_to_rgb", side_effect=leaky):
            _, _, blue = build_ramp(KELVIN_MIN, 1.0, zero_blue=True)
        self.assertEqual(set(blue), {0}, "blue survived a curve that returned blue")

    def test_a_leaky_curve_would_otherwise_show_up(self):
        # Guards the test above from quietly becoming vacuous: the same patched
        # curve must produce blue when zero_blue is off, or the assertion there
        # proves nothing.
        leaky = lambda kelvin: (1.0, 1.0, 1.0)  # noqa: E731
        with mock.patch("gamma.kelvin_to_rgb", side_effect=leaky):
            _, _, blue = build_ramp(KELVIN_MIN, 1.0, zero_blue=False)
        self.assertNotEqual(set(blue), {0})

    def test_temperature_is_pinned_regardless_of_what_was_asked_for(self):
        # The slider greys out in the UI while this mode is on; this is the
        # matching guarantee underneath, so a stale slider value can't leak in.
        pinned = build_ramp(KELVIN_MIN, 1.0, zero_blue=True)
        for kelvin in [KELVIN_MIN, 2700, 4000, KELVIN_NEUTRAL, 99999]:
            self.assertEqual(
                build_ramp(kelvin, 1.0, zero_blue=True), pinned, f"{kelvin}K leaked in"
            )

    def test_green_comes_down_with_it(self):
        # Zeroing blue at 6500K would leave a sickly green-white. Pinning to
        # KELVIN_MIN is what makes the result read as candle-amber, and this
        # is the assertion that notices if the pinning is ever dropped.
        _, green, _ = build_ramp(KELVIN_NEUTRAL, 1.0, zero_blue=True)
        top = RAMP_SIZE - 1
        self.assertLess(green[top] / 65535, 0.5, "green left too high to read as amber")

    def test_red_still_leads(self):
        red, green, _ = build_ramp(KELVIN_NEUTRAL, 1.0, zero_blue=True)
        top = RAMP_SIZE - 1
        self.assertGreater(red[top], green[top], "amber needs red above green")


class TestKelvinToHex(unittest.TestCase):
    """The preview swatch — what the user is promised before they let go."""

    def test_neutral_full_brightness_is_pure_white(self):
        self.assertEqual(kelvin_to_hex(KELVIN_NEUTRAL, 1.0), "#ffffff")

    def test_always_a_well_formed_colour(self):
        for kelvin in SLIDER:
            for brightness in (0.15, 0.5, 1.0):
                for zero_blue in (False, True):
                    swatch = kelvin_to_hex(kelvin, brightness, zero_blue)
                    self.assertRegex(
                        swatch, r"^#[0-9a-f]{6}$", f"malformed at {kelvin}K"
                    )

    def test_swatch_agrees_with_the_ramp_it_previews(self):
        # The swatch is a promise about what the screen will do. If it drifts
        # from build_ramp the preview lies, which is worse than no preview.
        for kelvin in (KELVIN_MIN, 2700, 4000, KELVIN_NEUTRAL):
            for zero_blue in (False, True):
                swatch = kelvin_to_hex(kelvin, 1.0, zero_blue)
                channels = build_ramp(kelvin, 1.0, zero_blue)
                top = RAMP_SIZE - 1
                for index, name in enumerate("rgb"):
                    from_swatch = int(swatch[1 + index * 2 : 3 + index * 2], 16)
                    from_ramp = round(channels[index][top] / 65535 * 255)
                    self.assertLessEqual(
                        abs(from_swatch - from_ramp),
                        1,
                        f"{name} swatch disagrees with ramp at {kelvin}K",
                    )

    def test_zero_blue_shows_no_blue(self):
        self.assertEqual(kelvin_to_hex(KELVIN_NEUTRAL, 1.0, zero_blue=True)[5:7], "00")

    def test_brightness_floor_matches_the_ramp(self):
        self.assertEqual(kelvin_to_hex(2700, 0.0), kelvin_to_hex(2700, 0.15))


if __name__ == "__main__":
    unittest.main()
