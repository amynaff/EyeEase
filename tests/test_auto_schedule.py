"""test_auto_schedule.py — parsing, solar maths, and the fade curve.

Like the gamma tests, these cover code whose failures are quiet. A sunset
computed an hour off doesn't raise; the screen just warms at the wrong time
and the user assumes that's how the app works. A coordinate parser that
silently drops a hemisphere letter turns 74°W into 74°E — a valid number,
a location 10,000 miles away, and no error anywhere.

Every datetime here carries an explicit timezone. Schedule calls
datetime.now().astimezone() when it isn't given one, so tests that passed
naive values would quietly depend on the timezone of whichever machine ran
them, and would drift into and out of failure twice a year.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_schedule import (  # noqa: E402
    DEFAULT_FADE_MINUTES,
    ELEVATION_DAY,
    ELEVATION_NIGHT,
    Schedule,
    _smoothstep,
    elevation_night_fraction,
    parse_hhmm,
    parse_latitude,
    parse_longitude,
    solar_elevation,
    solar_events,
)

UTC = timezone.utc

# Somewhere mid-latitude and somewhere polar, for the two branches of the
# sunrise equation.
LONDON = (51.5, -0.13)
SVALBARD = (78.2, 15.6)
EQUATOR = (0.0, 0.0)

EQUINOX = datetime(2026, 3, 20, 12, 0, tzinfo=UTC)
MIDSUMMER = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
MIDWINTER = datetime(2026, 12, 21, 12, 0, tzinfo=UTC)


class TestParseHhmm(unittest.TestCase):
    def test_accepts_ordinary_times(self):
        self.assertEqual(parse_hhmm("20:00"), (20, 0))
        self.assertEqual(parse_hhmm("07:30"), (7, 30))
        self.assertEqual(parse_hhmm("7:05"), (7, 5))
        self.assertEqual(parse_hhmm("00:00"), (0, 0))
        self.assertEqual(parse_hhmm("23:59"), (23, 59))

    def test_tolerates_surrounding_space(self):
        self.assertEqual(parse_hhmm("  20:00  "), (20, 0))

    def test_rejects_everything_that_is_not_a_time(self):
        # Each of these must come back None rather than raising: the panel
        # calls this on every keystroke while someone is still typing.
        for bad in [
            "24:00", "25:00", "12:60", "-1:00", "12:-5",
            "12", "", "   ", "abc", "12:ab", "12:00:00", ":", "::",
            None, 1200,
        ]:
            self.assertIsNone(parse_hhmm(bad), f"accepted {bad!r}")


class TestParseCoordinates(unittest.TestCase):
    def test_plain_decimals(self):
        self.assertAlmostEqual(parse_latitude("51.5"), 51.5)
        self.assertAlmostEqual(parse_longitude("-0.13"), -0.13)
        self.assertAlmostEqual(parse_latitude("0"), 0.0)

    def test_hemisphere_letters_set_the_sign(self):
        # The failure this guards against is silent and enormous: dropping the
        # W turns New York into Kazakhstan, and every sunset after that is
        # wrong by nine hours with nothing on screen to say so.
        self.assertAlmostEqual(parse_latitude("40.7 N"), 40.7)
        self.assertAlmostEqual(parse_latitude("40.7 S"), -40.7)
        self.assertAlmostEqual(parse_longitude("74.0 W"), -74.0)
        self.assertAlmostEqual(parse_longitude("74.0 E"), 74.0)

    def test_letters_work_without_a_space_and_in_lower_case(self):
        self.assertAlmostEqual(parse_longitude("74.0w"), -74.0)
        self.assertAlmostEqual(parse_latitude("40.7n"), 40.7)

    def test_degree_sign_is_ignored(self):
        self.assertAlmostEqual(parse_latitude("51.5°"), 51.5)
        self.assertAlmostEqual(parse_longitude("0.13° W"), -0.13)

    def test_range_limits_differ_between_latitude_and_longitude(self):
        self.assertAlmostEqual(parse_latitude("90"), 90.0)
        self.assertAlmostEqual(parse_latitude("-90"), -90.0)
        self.assertIsNone(parse_latitude("90.1"))
        self.assertIsNone(parse_latitude("120"))
        # 120 is a perfectly good longitude, which is the point of two limits.
        self.assertAlmostEqual(parse_longitude("120"), 120.0)
        self.assertAlmostEqual(parse_longitude("180"), 180.0)
        self.assertIsNone(parse_longitude("180.1"))

    def test_rejects_junk(self):
        for bad in ["", "   ", "abc", "N", "1.2.3", "--5", None]:
            self.assertIsNone(parse_latitude(bad), f"latitude accepted {bad!r}")
            self.assertIsNone(parse_longitude(bad), f"longitude accepted {bad!r}")


class TestSmoothstep(unittest.TestCase):
    def test_endpoints_are_exact(self):
        self.assertEqual(_smoothstep(0.0), 0.0)
        self.assertEqual(_smoothstep(1.0), 1.0)

    def test_clamps_outside_the_unit_interval(self):
        self.assertEqual(_smoothstep(-5.0), 0.0)
        self.assertEqual(_smoothstep(5.0), 1.0)

    def test_midpoint_and_symmetry(self):
        self.assertAlmostEqual(_smoothstep(0.5), 0.5)
        for t in (0.1, 0.25, 0.4):
            self.assertAlmostEqual(_smoothstep(t) + _smoothstep(1 - t), 1.0)

    def test_it_actually_eases_rather_than_running_straight(self):
        # Endpoints, midpoint and monotonicity are all equally true of a plain
        # linear ramp, so on their own they'd let `return t` pass as a
        # smoothstep. The distinguishing property is the S: the curve starts
        # slower than linear and finishes slower than linear, which is what
        # stops the screen visibly lurching when a fade begins and ends.
        self.assertLess(_smoothstep(0.25), 0.25)
        self.assertLess(_smoothstep(0.1), 0.1)
        self.assertGreater(_smoothstep(0.75), 0.75)
        self.assertGreater(_smoothstep(0.9), 0.9)

    def test_the_curve_is_flat_at_both_ends(self):
        # The reason the easing is imperceptible at the boundaries: the rate of
        # change approaches zero there, so warmth arrives and departs gradually
        # instead of switching on at a detectable instant.
        step = 1e-4
        opening_rate = (_smoothstep(step) - _smoothstep(0.0)) / step
        closing_rate = (_smoothstep(1.0) - _smoothstep(1 - step)) / step
        middle_rate = (_smoothstep(0.5 + step) - _smoothstep(0.5)) / step
        self.assertLess(opening_rate, 0.01, "fade starts abruptly")
        self.assertLess(closing_rate, 0.01, "fade ends abruptly")
        self.assertGreater(middle_rate, 1.0, "fade never gets going")

    def test_monotonic(self):
        previous = -1.0
        for i in range(101):
            value = _smoothstep(i / 100)
            self.assertGreaterEqual(value, previous)
            previous = value


class TestElevationNightFraction(unittest.TestCase):
    def test_anchored_at_the_documented_angles(self):
        self.assertAlmostEqual(elevation_night_fraction(ELEVATION_DAY), 0.0)
        self.assertAlmostEqual(elevation_night_fraction(ELEVATION_NIGHT), 1.0)

    def test_saturates_beyond_them(self):
        self.assertEqual(elevation_night_fraction(90.0), 0.0)
        self.assertEqual(elevation_night_fraction(-90.0), 1.0)

    def test_falls_as_the_sun_rises(self):
        previous = 2.0
        for tenths in range(-200, 200):
            value = elevation_night_fraction(tenths / 10)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
            self.assertLessEqual(value, previous + 1e-9)
            previous = value


class TestSolarEvents(unittest.TestCase):
    def test_sunrise_comes_before_sunset(self):
        for lat, lon in (LONDON, EQUATOR):
            for day in (EQUINOX, MIDSUMMER, MIDWINTER):
                sunrise, sunset = solar_events(lat, lon, day)
                self.assertIsNotNone(sunrise)
                self.assertLess(sunrise, sunset, f"at {lat},{lon} on {day.date()}")

    def test_equator_has_a_twelve_hour_day_year_round(self):
        for day in (EQUINOX, MIDSUMMER, MIDWINTER):
            sunrise, sunset = solar_events(*EQUATOR, day)
            hours = (sunset - sunrise).total_seconds() / 3600
            # Slightly over 12 because SOLAR_ZENITH_DEG counts refraction and
            # the sun's radius, which lengthens every day a little.
            self.assertTrue(12.0 < hours < 12.3, f"{hours:.2f}h on {day.date()}")

    def test_london_summer_days_are_much_longer_than_winter_ones(self):
        summer = solar_events(*LONDON, MIDSUMMER)
        winter = solar_events(*LONDON, MIDWINTER)
        summer_hours = (summer[1] - summer[0]).total_seconds() / 3600
        winter_hours = (winter[1] - winter[0]).total_seconds() / 3600
        self.assertTrue(16.0 < summer_hours < 17.0, f"{summer_hours:.2f}h")
        self.assertTrue(7.5 < winter_hours < 8.5, f"{winter_hours:.2f}h")

    def test_equinox_is_close_to_twelve_hours_everywhere(self):
        for lat, lon in (LONDON, EQUATOR):
            sunrise, sunset = solar_events(lat, lon, EQUINOX)
            hours = (sunset - sunrise).total_seconds() / 3600
            self.assertTrue(11.8 < hours < 12.6, f"{hours:.2f}h at {lat}")

    def test_polar_day_and_polar_night_report_no_events(self):
        # The branch that exists so the app doesn't crash above the Arctic
        # Circle. Returning (None, None) is what makes the schedule fall back
        # rather than raise.
        self.assertEqual(solar_events(*SVALBARD, MIDSUMMER), (None, None))
        self.assertEqual(solar_events(*SVALBARD, MIDWINTER), (None, None))

    def test_polar_locations_still_work_at_the_equinox(self):
        sunrise, sunset = solar_events(*SVALBARD, EQUINOX)
        self.assertIsNotNone(sunrise, "Svalbard has a normal day at the equinox")
        self.assertLess(sunrise, sunset)

    def test_results_are_timezone_aware(self):
        # _from_julian returns UTC. If it ever returned naive datetimes the
        # comparisons in Schedule would raise on the first tick.
        for moment in solar_events(*LONDON, EQUINOX):
            self.assertIsNotNone(moment.tzinfo)


class TestSolarElevation(unittest.TestCase):
    def test_stays_within_the_physical_range(self):
        moment = datetime(2026, 5, 1, tzinfo=UTC)
        for _ in range(48):
            for lat, lon in (LONDON, EQUATOR, SVALBARD):
                elevation = solar_elevation(lat, lon, moment)
                self.assertGreaterEqual(elevation, -90.0)
                self.assertLessEqual(elevation, 90.0)
            moment += timedelta(hours=1)

    def test_sun_is_overhead_at_equatorial_noon_on_the_equinox(self):
        self.assertGreater(solar_elevation(*EQUATOR, EQUINOX), 85.0)

    def test_sun_is_far_below_the_horizon_at_midnight(self):
        midnight = datetime(2026, 3, 20, 0, 0, tzinfo=UTC)
        self.assertLess(solar_elevation(*EQUATOR, midnight), -85.0)

    def test_polar_summer_sun_never_sets(self):
        # The physical fact behind solar_events returning (None, None): over
        # a full day at Svalbard in June, elevation stays above the horizon.
        moment = MIDSUMMER.replace(hour=0)
        for _ in range(24):
            self.assertGreater(solar_elevation(*SVALBARD, moment), 0.0)
            moment += timedelta(hours=1)

    def test_agrees_with_the_sunset_it_reports(self):
        # Two independent routes to the same quantity — if the shared
        # _sun_for_day ever drifts, these stop matching.
        _, sunset = solar_events(*LONDON, EQUINOX)
        elevation = solar_elevation(*LONDON, sunset)
        self.assertLess(abs(elevation - (-0.833)), 0.5, f"{elevation:.3f}° at sunset")


class TestFixedSchedule(unittest.TestCase):
    """20:00 to 07:00, the default, with a 45-minute fade."""

    def setUp(self):
        self.schedule = Schedule(mode="fixed", start="20:00", end="07:00")

    def at(self, hour, minute=0):
        return datetime(2026, 1, 15, hour, minute, tzinfo=UTC)

    def test_midday_is_fully_neutral(self):
        self.assertEqual(self.schedule.night_fraction(self.at(12)), 0.0)

    def test_deep_night_is_fully_warm(self):
        self.assertEqual(self.schedule.night_fraction(self.at(3)), 1.0)

    def test_the_fade_has_not_started_at_the_instant_of_the_event(self):
        self.assertEqual(self.schedule.night_fraction(self.at(20, 0)), 0.0)
        self.assertEqual(self.schedule.night_fraction(self.at(7, 0)), 1.0)

    def test_the_fade_completes_after_exactly_the_fade_window(self):
        end = self.at(20, DEFAULT_FADE_MINUTES)
        self.assertAlmostEqual(self.schedule.night_fraction(end), 1.0)
        morning = self.at(7, DEFAULT_FADE_MINUTES)
        self.assertAlmostEqual(self.schedule.night_fraction(morning), 0.0)

    def test_halfway_through_the_fade_is_halfway_warm(self):
        halfway = self.at(20, DEFAULT_FADE_MINUTES // 2)
        self.assertAlmostEqual(self.schedule.night_fraction(halfway), 0.5, places=1)

    def test_the_fade_rises_without_reversing(self):
        previous = -1.0
        for minute in range(0, DEFAULT_FADE_MINUTES + 1):
            value = self.schedule.night_fraction(self.at(20, minute))
            self.assertGreaterEqual(value, previous - 1e-9, f"dipped at 20:{minute:02d}")
            previous = value

    def test_fraction_stays_in_range_across_a_full_day(self):
        moment = self.at(0)
        for _ in range(24 * 12):  # every five minutes
            value = self.schedule.night_fraction(moment)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
            moment += timedelta(minutes=5)

    def test_fading_is_true_only_during_a_transition(self):
        self.assertTrue(self.schedule.fading(self.at(20, 10)))
        self.assertFalse(self.schedule.fading(self.at(21, 30)))
        self.assertFalse(self.schedule.fading(self.at(12)))
        # True at the exact moment of the event, which is the case the
        # docstring says night_fraction alone would get wrong.
        self.assertTrue(self.schedule.fading(self.at(20, 0)))

    def test_next_event_looks_forward_only(self):
        when, going_to_night = self.schedule.next_event(self.at(12))
        self.assertTrue(going_to_night)
        self.assertEqual((when.hour, when.minute), (20, 0))

        when, going_to_night = self.schedule.next_event(self.at(22))
        self.assertFalse(going_to_night)
        self.assertEqual((when.hour, when.minute), (7, 0))

    def test_next_change_finds_the_start_of_the_fade(self):
        change = self.schedule.next_change(self.at(12))
        self.assertIsNotNone(change)
        self.assertEqual(change.hour, 20)
        self.assertLess(change.minute, 15)

    def test_a_night_that_does_not_straddle_midnight(self):
        # 09:00 to 17:00 — unusual, but nothing forbids it, and the
        # yesterday/today/tomorrow event walk should handle it the same way.
        daytime = Schedule(mode="fixed", start="09:00", end="17:00")
        self.assertEqual(daytime.night_fraction(self.at(12)), 1.0)
        self.assertEqual(daytime.night_fraction(self.at(3)), 0.0)


class TestSolarSchedule(unittest.TestCase):
    def test_fraction_stays_in_range_across_a_year(self):
        schedule = Schedule(mode="solar", latitude=LONDON[0], longitude=LONDON[1])
        moment = datetime(2026, 1, 1, tzinfo=UTC)
        for _ in range(365 * 4):  # every six hours
            value = schedule.night_fraction(moment)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
            moment += timedelta(hours=6)

    def test_warm_at_night_and_neutral_at_noon(self):
        schedule = Schedule(mode="solar", latitude=EQUATOR[0], longitude=EQUATOR[1])
        self.assertAlmostEqual(schedule.night_fraction(EQUINOX), 0.0)
        midnight = datetime(2026, 3, 20, 0, 0, tzinfo=UTC)
        self.assertAlmostEqual(schedule.night_fraction(midnight), 1.0)

    def test_warming_begins_before_the_sun_reaches_the_horizon(self):
        # ELEVATION_DAY is deliberately 10° above the horizon, so the screen
        # is already easing while the sun is still up. This is the assertion
        # behind the README's claim that quoting "neutral until sunset" would
        # describe a screen that has already started changing.
        schedule = Schedule(mode="solar", latitude=LONDON[0], longitude=LONDON[1])
        _, sunset = solar_events(*LONDON, EQUINOX)
        self.assertGreater(schedule.night_fraction(sunset - timedelta(minutes=30)), 0.0)

    def test_polar_day_falls_back_instead_of_crashing(self):
        schedule = Schedule(mode="solar", latitude=SVALBARD[0], longitude=SVALBARD[1])
        value = schedule.night_fraction(MIDSUMMER)
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)
        self.assertEqual(schedule._events_for(MIDSUMMER), [])


class TestScheduleConfiguration(unittest.TestCase):
    def test_is_usable_requires_coordinates_in_solar_mode(self):
        self.assertFalse(Schedule(mode="solar").is_usable())
        self.assertFalse(Schedule(mode="solar", latitude=51.5).is_usable())
        self.assertTrue(Schedule(mode="solar", latitude=51.5, longitude=-0.13).is_usable())

    def test_is_usable_requires_valid_times_in_fixed_mode(self):
        self.assertTrue(Schedule(mode="fixed").is_usable())
        self.assertFalse(Schedule(mode="fixed", start="nonsense").is_usable())
        self.assertFalse(Schedule(mode="fixed", end="99:99").is_usable())

    def test_fade_minutes_cannot_be_zero(self):
        # A zero fade would divide by zero in night_fraction.
        self.assertEqual(Schedule(fade_minutes=0).fade_minutes, 1)
        self.assertEqual(Schedule(fade_minutes=-30).fade_minutes, 1)

    def test_unusable_schedules_say_which_field_is_missing(self):
        self.assertEqual(Schedule(mode="solar").status_line(), "enter coordinates")
        self.assertEqual(Schedule(mode="fixed", start="x").status_line(), "set a time")

    def test_status_line_always_returns_something_printable(self):
        schedule = Schedule(mode="fixed", start="20:00", end="07:00")
        moment = datetime(2026, 1, 15, tzinfo=UTC)
        for _ in range(48):
            line = schedule.status_line(moment)
            self.assertIsInstance(line, str)
            self.assertTrue(line.strip())
            moment += timedelta(minutes=30)

    def test_settings_survive_a_save_and_reload(self):
        original = Schedule(
            mode="solar", start="21:30", end="06:15",
            latitude=-33.9, longitude=151.2, fade_minutes=20,
        )
        restored = Schedule.from_dict(original.to_dict())
        self.assertEqual(restored.to_dict(), original.to_dict())

    def test_from_dict_fills_in_defaults_for_a_missing_or_empty_file(self):
        for data in (None, {}):
            schedule = Schedule.from_dict(data)
            self.assertEqual(schedule.mode, "fixed")
            self.assertTrue(schedule.is_usable())


if __name__ == "__main__":
    unittest.main()
