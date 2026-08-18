"""
schedule.py — decides how warm the screen should be at any given moment.

Two modes:

  fixed  — warm between two clock times you pick (e.g. 20:00 to 07:00).
           Works anywhere, needs nothing but a clock.
  solar  — warm between sunset and sunrise, computed from your latitude and
           longitude. Needs coordinates, which you enter yourself.

There is deliberately no location lookup. Guessing a latitude from the time
zone would be wrong by hundreds of miles (a zone is a band of longitude, not
a point), and an IP geolocation call would mean this app talks to the network
and learns where you are — neither is worth it for a utility that dims a
screen. Solar mode is opt-in and offline; fixed mode is the default.

The transition is gradual, not a switch: each event starts a fade lasting
`fade_minutes`, so the screen drifts warm over the evening the way daylight
actually goes.
"""

import math
from datetime import datetime, timedelta, timezone

# How far the sun sits below the horizon at the moment we call it sunrise or
# sunset — the standard value, accounting for atmospheric refraction and the
# sun's radius.
SOLAR_ZENITH_DEG = -0.833

DEFAULT_FADE_MINUTES = 45
DEFAULT_FIXED_START = "20:00"
DEFAULT_FIXED_END = "07:00"


# -- solar math ---------------------------------------------------------
# Standard sunrise equation. Accurate to roughly a minute for ordinary
# latitudes, which is far tighter than matters here — nobody notices their
# screen starting to warm 60 seconds early.


def _to_julian(moment: datetime) -> float:
    return moment.timestamp() / 86400.0 + 2440587.5


def _from_julian(julian: float) -> datetime:
    return datetime.fromtimestamp((julian - 2440587.5) * 86400.0, tz=timezone.utc)


def _sun_for_day(longitude: float, day: datetime):
    """(declination in radians, solar transit as a Julian date) for a date.

    Shared by the sunrise equation and the elevation calculation, which need
    exactly the same two quantities — the sun's tilt that day, and the moment
    it crosses due south.
    """
    # Julian day number for solar noon on the requested date.
    midday = day.replace(hour=12, minute=0, second=0, microsecond=0)
    n = round(_to_julian(midday) - 2451545.0 + 0.0008)

    mean_solar_noon = n - longitude / 360.0

    # Solar mean anomaly.
    m = math.radians((357.5291 + 0.98560028 * mean_solar_noon) % 360.0)

    # Equation of the centre — corrects the mean anomaly for the Earth's
    # elliptical orbit.
    c = (
        1.9148 * math.sin(m)
        + 0.0200 * math.sin(2 * m)
        + 0.0003 * math.sin(3 * m)
    )

    ecliptic_lon = math.radians((math.degrees(m) + c + 180 + 102.9372) % 360.0)

    solar_transit = (
        2451545.0
        + mean_solar_noon
        + 0.0053 * math.sin(m)
        - 0.0069 * math.sin(2 * ecliptic_lon)
    )

    declination = math.asin(
        math.sin(ecliptic_lon) * math.sin(math.radians(23.44))
    )
    return declination, solar_transit


def solar_elevation(latitude: float, longitude: float, when: datetime) -> float:
    """How high the sun is above the horizon, in degrees, at a moment.

    Negative below the horizon. This is what makes the warming curve a real
    curve: sunset is a single instant, but elevation changes continuously all
    day, and how fast it changes depends on latitude and time of year. A
    January evening in Reykjavík slides toward night far more gradually than
    a June evening in Quito, and driving warmth from this reproduces that
    instead of ramping for a fixed number of minutes everywhere.
    """
    declination, transit = _sun_for_day(longitude, when)

    # Hour angle: the Earth turns 360° per day, measured from solar noon.
    hour_angle = math.radians((_to_julian(when) - transit) * 360.0)

    lat = math.radians(latitude)
    sin_elevation = (
        math.sin(lat) * math.sin(declination)
        + math.cos(lat) * math.cos(declination) * math.cos(hour_angle)
    )
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_elevation))))


def solar_events(latitude: float, longitude: float, day: datetime):
    """Returns (sunrise, sunset) as aware UTC datetimes for the given day.

    Returns (None, None) when the sun doesn't rise or set at all — the polar
    summer/winter case, where the hour-angle equation has no solution.
    """
    declination, solar_transit = _sun_for_day(longitude, day)

    lat = math.radians(latitude)
    numerator = math.sin(math.radians(SOLAR_ZENITH_DEG)) - math.sin(lat) * math.sin(
        declination
    )
    denominator = math.cos(lat) * math.cos(declination)
    if denominator == 0:
        return (None, None)

    cos_hour_angle = numerator / denominator
    if not -1.0 <= cos_hour_angle <= 1.0:
        # Sun never crosses the horizon on this date at this latitude.
        return (None, None)

    hour_angle = math.degrees(math.acos(cos_hour_angle))

    sunset = _from_julian(solar_transit + hour_angle / 360.0)
    sunrise = _from_julian(solar_transit - hour_angle / 360.0)
    return (sunrise, sunset)


# -- schedule -----------------------------------------------------------


def parse_hhmm(text: str):
    """'20:00' -> (20, 0). Returns None if it isn't a valid time of day."""
    try:
        hours, minutes = text.strip().split(":")
        h, m = int(hours), int(minutes)
    except (ValueError, AttributeError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return (h, m)


def _parse_coordinate(text, limit: float):
    """Parse a signed decimal degree, or None if it isn't one.

    Accepts a trailing hemisphere letter ("40.7 N", "74.0 W") because that's
    how coordinates are usually written down, and W/S mean a negative value.
    """
    if text is None:
        return None
    cleaned = str(text).strip().upper().replace("°", "")
    if not cleaned:
        return None

    sign = 1.0
    if cleaned and cleaned[-1] in "NSEW":
        if cleaned[-1] in "SW":
            sign = -1.0
        cleaned = cleaned[:-1].strip()

    try:
        value = float(cleaned)
    except ValueError:
        return None

    value *= sign
    if not -limit <= value <= limit:
        return None
    return value


def parse_latitude(text):
    return _parse_coordinate(text, 90.0)


def parse_longitude(text):
    return _parse_coordinate(text, 180.0)


# Where the warming begins and ends, in degrees of sun elevation.
#
# ELEVATION_DAY is deliberately above the horizon: the light is already
# reddening and dimming well before the sun touches it, so waiting for sunset
# itself would make the change arrive late and then hurry. ELEVATION_NIGHT is
# the standard civil-twilight angle — the point at which outdoor light is
# genuinely gone.
ELEVATION_DAY = 10.0
ELEVATION_NIGHT = -6.0


def elevation_night_fraction(elevation: float) -> float:
    """Sun elevation -> how much of the night setting applies, 0.0 to 1.0."""
    span = ELEVATION_DAY - ELEVATION_NIGHT
    return _smoothstep((ELEVATION_DAY - elevation) / span)


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


class Schedule:
    """Turns 'what time is it' into 'how much of the night setting applies'."""

    def __init__(
        self,
        mode="fixed",
        start=DEFAULT_FIXED_START,
        end=DEFAULT_FIXED_END,
        latitude=None,
        longitude=None,
        fade_minutes=DEFAULT_FADE_MINUTES,
    ):
        self.mode = mode  # 'fixed' or 'solar'
        self.start = start
        self.end = end
        self.latitude = latitude
        self.longitude = longitude
        self.fade_minutes = max(1, int(fade_minutes))

    def is_usable(self):
        """Whether this schedule can actually produce times right now."""
        if self.mode == "solar":
            return self.latitude is not None and self.longitude is not None
        return parse_hhmm(self.start) is not None and parse_hhmm(self.end) is not None

    # -- event list ------------------------------------------------------
    def _events_for(self, day: datetime):
        """[(when, going_to_night)] for the given local day, or [] if none."""
        if self.mode == "solar":
            if self.latitude is None or self.longitude is None:
                return []
            sunrise, sunset = solar_events(self.latitude, self.longitude, day)
            if sunrise is None or sunset is None:
                return []
            return [(sunrise.astimezone(), False), (sunset.astimezone(), True)]

        start = parse_hhmm(self.start)
        end = parse_hhmm(self.end)
        if start is None or end is None:
            return []
        return [
            (day.replace(hour=end[0], minute=end[1], second=0, microsecond=0), False),
            (
                day.replace(hour=start[0], minute=start[1], second=0, microsecond=0),
                True,
            ),
        ]

    def _all_events(self, now: datetime):
        """Events across yesterday/today/tomorrow, sorted.

        Three days rather than one because the night straddles midnight — at
        01:00 the event that matters is yesterday's sunset, and at 23:00 the
        next one is tomorrow's sunrise.
        """
        events = []
        for offset in (-1, 0, 1):
            events.extend(self._events_for(now + timedelta(days=offset)))
        return sorted(events, key=lambda e: e[0])

    # -- the actual question ---------------------------------------------
    def night_fraction(self, now=None):
        """0.0 = full daylight (screen untouched), 1.0 = full night setting.

        Values in between mean a fade is in progress.
        """
        now = now or datetime.now().astimezone()

        # With coordinates we can do better than a timed ramp. Elevation is a
        # continuous quantity, so the screen tracks the sun actually going
        # down rather than starting a stopwatch when it crosses the horizon.
        # The curve's shape then comes from your latitude and the date, which
        # is the whole point of asking for coordinates in the first place.
        if self.mode == "solar" and self.latitude is not None and self.longitude is not None:
            return elevation_night_fraction(
                solar_elevation(self.latitude, self.longitude, now)
            )

        events = self._all_events(now)
        if not events:
            return 0.0

        past = [e for e in events if e[0] <= now]
        if not past:
            # Before every event we know about — we're in whatever state the
            # first upcoming event is transitioning *away* from.
            return 0.0 if events[0][1] else 1.0

        when, going_to_night = past[-1]
        target = 1.0 if going_to_night else 0.0
        previous = 1.0 - target

        elapsed = (now - when).total_seconds() / 60.0
        return previous + (target - previous) * _smoothstep(elapsed / self.fade_minutes)

    def fading(self, now=None):
        """True while a transition is actually in progress.

        Asks 'how long since the last event' rather than 'is the fraction
        between 0 and 1', because at the exact moment of an event the
        fraction is still 0 (or 1) even though the fade has just begun.
        """
        now = now or datetime.now().astimezone()
        past = [e for e in self._all_events(now) if e[0] <= now]
        if not past:
            return False
        elapsed = (now - past[-1][0]).total_seconds() / 60.0
        return elapsed < self.fade_minutes

    def next_event(self, now=None):
        """(when, going_to_night) for the next upcoming change, or None."""
        now = now or datetime.now().astimezone()
        upcoming = [e for e in self._all_events(now) if e[0] > now]
        return upcoming[0] if upcoming else None

    def _elevation_driven(self):
        return (
            self.mode == "solar"
            and self.latitude is not None
            and self.longitude is not None
        )

    def next_change(self, now=None, horizon_hours=24):
        """When the screen next starts or finishes changing.

        Sunset is the wrong thing to quote once warmth follows elevation:
        the screen begins warming while the sun is still up, so promising
        "neutral until sunset" describes a screen that is already changing.
        This finds the moment the curve itself crosses in or out of a fade,
        by walking it forward — there's no closed form for "when does
        elevation reach 10°" that's worth the algebra.
        """
        now = now or datetime.now().astimezone()
        start = self.night_fraction(now)
        settled_now = start <= 0.02 or start >= 0.98

        step = timedelta(minutes=2)
        t = now
        for _ in range(int(horizon_hours * 30)):
            t += step
            fraction = self.night_fraction(t)
            settled = fraction <= 0.02 or fraction >= 0.98
            if settled != settled_now:
                return t
        return None

    def status_line(self, now=None):
        """Short human description of what the schedule is doing, for the UI."""
        now = now or datetime.now().astimezone()
        if not self.is_usable():
            return "enter coordinates" if self.mode == "solar" else "set a time"

        if self._elevation_driven():
            fraction = self.night_fraction(now)
            if 0.02 < fraction < 0.98:
                return f"easing — {int(round(fraction * 100))}% warm"
            change = self.next_change(now)
            if change is None:
                return "warm all day" if fraction >= 0.98 else "neutral all day"
            when = change.strftime("%H:%M")
            return f"warm until {when}" if fraction >= 0.98 else f"neutral until {when}"

        fraction = self.night_fraction(now)
        upcoming = self.next_event(now)
        if upcoming is None:
            return "no sunrise or sunset today"

        when, going_to_night = upcoming
        delta = when - now
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes = remainder // 60
        away = f"{hours}h {minutes}m" if hours else f"{minutes}m"

        if self.fading(now):
            return f"easing — {int(round(fraction * 100))}% warm"
        if fraction >= 0.5:
            return f"warm until {when.strftime('%H:%M')} ({away})"
        return f"neutral until {when.strftime('%H:%M')} ({away})"

    # -- persistence -----------------------------------------------------
    def to_dict(self):
        return {
            "mode": self.mode,
            "start": self.start,
            "end": self.end,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "fade_minutes": self.fade_minutes,
        }

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        return cls(
            mode=data.get("mode", "fixed"),
            start=data.get("start", DEFAULT_FIXED_START),
            end=data.get("end", DEFAULT_FIXED_END),
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            fade_minutes=data.get("fade_minutes", DEFAULT_FADE_MINUTES),
        )
