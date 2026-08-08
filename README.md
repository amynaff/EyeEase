# EyeEase

Free, minimal blue-light blocker for Mac and Windows — same underlying idea
as RedShift (gamma-table manipulation): two sliders, three presets, one EASE
button, an auto schedule, and it lives in the tray.

The palette is amber, not an alarm red, because amber is what the app itself
produces at evening temperatures — the brand is the colour the product makes.
The mark is an eye, defined once in `brand.py` and shared by the app icon,
the tray icon and the in-panel button.

## How it works, in one paragraph
Every screen redraws pixels through a "gamma ramp" — a lookup table that maps
input color to output color for red, green, and blue separately. This app
bends the green and blue curves down to match a blackbody radiator at a given
colour temperature, the same 6500K-to-1200K scale f.lux and Redshift use, so
less blue light reaches your eyes no matter what's on screen. Brightness
scales all three curves together as a software dim. `gamma.py` has the full
explanation inline.

Bending green and blue down *together* would only desaturate toward red. What
makes a screen look warm rather than red is the gap between the two curves —
blue falls away fast while green falls slowly — which is exactly what the
blackbody curve in `kelvin_to_rgb()` produces.

## Setup
Requires Python 3.9+ with Tk support.

On macOS, check `python3 -c "import tkinter; print(tkinter.TkVersion)"` before
anything else. If `which python3` resolves to Xcode's Command Line Tools
(`/Applications/Xcode.app/Contents/Developer/usr/bin/python3` or similar),
it links against the ancient system Tcl/Tk 8.5, which is unmaintained and
renders windows as blank white on modern macOS — the panel builds fine, it
just never paints. Use a Python with Tk 8.6+ instead, e.g.:

```
brew install python-tk@3.14   # or whichever python version you use
```

then run everything below with that `python3` (a venv keeps it isolated:
`python3 -m venv .venv && source .venv/bin/activate`).

```
pip3 install -r requirements.txt
```

On macOS, if this fails while building `pyobjc-core` with a clang error
about `default-const-init-var-unsafe`, it's a strict-warnings issue between
that package and newer Xcode toolchains, not a problem with this project.
Work around it with:

```
CFLAGS="-Wno-error=default-const-init-var-unsafe" pip3 install -r requirements.txt
```

## Run it
```
python3 main.py
```

A small panel appears with:
- **Warmth slider** — vertical; drag up for warmer. Reads out in Kelvin,
  6500K (screen untouched) down to 1200K (deep amber, no blue left)
- **Brightness slider** — software dim, 15% to 100%
- **Live preview strip** — the colour a white pixel will actually become, so
  the sliders preview themselves
- **Three presets** — Reading (4000K), Evening (2700K), Sleep (1900K). The
  matching preset lights up when the sliders are sitting on its values
- **Auto schedule** — warms the screen on its own between two times you set
  (default 20:00 to 07:00), easing in over 45 minutes rather than snapping.
  While it's on, the sliders mean "what I want at *night*": the screen sits
  neutral during the day and slides toward those values across the fade, and
  the status line says which of those is happening right now. Presets still
  work — they move the night target. The EASE button still wins outright.
- **PWM-safe mode switch** — locks the built-in display's physical backlight
  to 100% and restores it on quit, so all dimming happens through the gamma
  ramp instead of the backlight's own PWM. Only the primary/built-in display
  is supported (external monitors need DDC/CI, which isn't wired up); if the
  OS won't grant brightness access the switch snaps back off instead of
  claiming to be active.
- **EASE button** — on/off. Switching off eases the screen back to normal but
  leaves the sliders where you set them, so switching back on returns to the
  same place. Preset changes and on/off ease over ~0.4s; dragging a slider
  applies instantly, since animating a drag just reads as input lag
- Closing the panel just hides it to the tray icon; use Quit from the tray
  menu to fully exit (this also resets your screen automatically)

Settings are saved to `~/.eyeease_settings.json` (debounced, so a slider drag
is one write rather than dozens) and restored next launch. Settings files
written before the Kelvin rewrite stored a 0.0-1.0 `warmth` value; it carries
over automatically as the equivalent slider position.

## Sunset/sunrise mode, and why it asks for coordinates
`auto_schedule.py` implements the standard sunrise equation, so the schedule
can run on real sunset and sunrise times instead of fixed clock times. It
needs a latitude and longitude, set in `~/.eyeease_settings.json`:

```json
"schedule": {"mode": "solar", "latitude": 40.7128, "longitude": -74.0060}
```

There is deliberately no automatic location lookup. Deriving latitude from
the time zone would be wrong by hundreds of miles — a zone is a band of
longitude, not a point — and an IP geolocation call would mean this app
talks to the network and learns where you are. Neither is a reasonable trade
for a utility that dims a screen, so solar mode is opt-in and entirely
offline. Fixed times remain the default and need nothing but a clock.

Accuracy is within about a minute at ordinary latitudes (checked against
published times for New York and Reykjavík). Polar day and polar night are
handled: when the sun never crosses the horizon there are no events, and the
panel says so rather than inventing a sunset.

There is not yet a UI for entering coordinates — solar mode is configured by
hand in the settings file. That's the obvious next step for it.

## What's deliberately left out of this version
PWM-safe mode only reaches the primary/built-in display. Extending it to
external monitors needs DDC/CI, which has no built-in OS API on either
platform — a good "v2" project once this base version feels solid.

Multi-monitor support for the gamma ramp itself is also stubbed out but not
wired up yet — notes on exactly where to add it are inline in `gamma.py`.

The macOS side of PWM-safe mode uses `CoreDisplay`, an undocumented private
framework (the same one tools like the `brightness` CLI rely on, since
Apple's public IOKit brightness API stopped working for the internal panel
on Apple Silicon). Private frameworks can move or disappear across macOS
versions without notice — if that happens, `enable_pwm_safe()` fails closed
(returns `False`) and the switch in the UI won't turn on, rather than
silently doing nothing.

## Packaging into a real .app (macOS)
Use the same Tk-capable `python3` called out in Setup above — PyInstaller
bundles whichever Tcl/Tk your interpreter is linked against, so building with
Xcode's stub `python3` ships the broken system Tk 8.5 inside the `.app` and
reproduces the blank-white-window issue for anyone who runs it.

```
CFLAGS="-Wno-error=default-const-init-var-unsafe" pip3 install pyinstaller
pyinstaller --noconfirm eyeease.spec
```

Produces `dist/EyeEase.app`, a double-clickable app with no Dock icon or
app-switcher entry (`LSUIElement` in the spec's `info_plist`) — it only ever
shows up as the tray icon, matching how it behaves when run from source.
`build/` and `dist/` are gitignored; rerun the command above to rebuild
after code changes.

## Packaging into a real .exe (Windows)
```
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm eyeease-windows.spec
```

Produces `dist/EyeEase.exe`, a single portable executable with no
console window. Must be run with PyInstaller *on Windows* — PyInstaller
can't cross-compile, and the spec deliberately refuses to run on any other
OS rather than silently producing a same-platform binary with the wrong
name (which is what a plain PyInstaller run would otherwise do).

This spec is untested on real Windows — there's no Windows machine in the
environment this was built in. The macOS `.app` above went through a full
verification pass (launched, tray icon clicked, panel shown, quit
confirmed); treat the Windows build as a starting point that needs the
same pass on real hardware before you'd trust it.
