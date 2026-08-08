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
- **Auto schedule** — warms the screen on its own, either between two clock
  times (default 20:00 to 07:00) or between real sunset and sunrise if you
  enter coordinates, easing in over 45 minutes rather than snapping.
  While it's on, the sliders mean "what I want at *night*": the screen sits
  neutral during the day and slides toward those values across the fade, and
  the status line says which of those is happening right now. Presets still
  work — they move the night target. The EASE button still wins outright.
- **PWM-safe mode switch** — locks the built-in display's physical backlight
  to 100% and restores it on quit, so all dimming happens through the gamma
  ramp instead of the backlight's own PWM. It re-asserts the lock every 30
  seconds, so pressing the brightness keys or macOS auto-brightness can't
  quietly drop you back into PWM dimming while the switch still claims to be
  on. Only the primary/built-in display is supported (external monitors need
  DDC/CI, which isn't wired up). If the backlight can't be driven, the switch
  refuses to engage and says so — see below.
- **Launch at login** — starts EyeEase when you log in. macOS gets a
  LaunchAgent plist in `~/Library/LaunchAgents`; Windows gets a value in the
  per-user `Run` key. Both are user-level, need no admin rights, and are a
  single file/value you can delete by hand.
- **EASE button** — on/off. Switching off eases the screen back to normal but
  leaves the sliders where you set them, so switching back on returns to the
  same place. Preset changes and on/off ease over ~0.4s; dragging a slider
  applies instantly, since animating a drag just reads as input lag
- The panel has no OS title bar — drag it by its header, and use the ✕ to
  hide it back to the tray. macOS draws the rounded corners and drop shadow
  on a borderless window itself, so none of that is faked in the app.
- Hiding the panel only hides it; use Quit from the tray menu to fully exit
  (this also resets your screen automatically)

Settings are saved to `~/.eyeease_settings.json` (debounced, so a slider drag
is one write rather than dozens) and restored next launch. Settings files
written before the Kelvin rewrite stored a 0.0-1.0 `warmth` value; it carries
over automatically as the equivalent slider position.

## Sunset/sunrise mode, and why it asks for coordinates
`auto_schedule.py` implements the standard sunrise equation, so the schedule
can run on real sunset and sunrise times instead of fixed clock times. Switch
the schedule card to **Sunset/sunrise** and type a latitude and longitude.

The fields accept plain signed decimals (`40.7128`, `-74.006`) or a trailing
hemisphere letter (`40.7 N`, `74.0 W`), since that's how coordinates are
usually written down. Anything out of range or unparseable reverts to the
last good value rather than sitting there looking accepted; clearing a field
unsets it, and the schedule then reports itself unusable instead of guessing
a location. Both modes keep their own settings, so switching back and forth
doesn't lose your times or your coordinates.

Sun times are shown in *your computer's* local time. Setting coordinates for
somewhere in another time zone is therefore legitimate but odd-looking — you
get that place's sunset expressed in your clock. Use where you actually are.

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

## Launch at login — one caveat
The login item records whatever is running when you switch it on. Packaged as
an `.app` or `.exe` that's the app itself, which is what you want. Toggled on
while running from source, it records *the interpreter that launched it* —
so a login item made from inside a throwaway virtualenv stops working the
moment that virtualenv is deleted, and macOS will quietly fail to start it.
Turn it on from the packaged build, or re-toggle it if you move your Python.

Nothing about it is mirrored into the settings file. The OS is the only real
answer to "does this launch at login" — a saved flag would go stale the
moment someone removed the login item by hand, and the switch would then be
claiming something untrue. `is_enabled()` always goes and looks.

macOS deliberately does not `launchctl load` the plist when you switch it on.
launchd reads `~/Library/LaunchAgents` at login, which is exactly when this
should take effect; loading it immediately would start a second copy of the
app on top of the one you're looking at. Switching it off does bootout, so
the setting doesn't linger until the next restart.

## What's deliberately left out of this version
PWM-safe mode only reaches the primary/built-in display. Extending it to
external monitors needs DDC/CI, which has no built-in OS API on either
platform — a good "v2" project once this base version feels solid.

Multi-monitor support for the gamma ramp itself is also stubbed out but not
wired up yet — notes on exactly where to add it are inline in `gamma.py`.

The borderless panel is done with `overrideredirect()`, which on macOS has to
be applied *after* the window has been mapped — calling it during setup
leaves a window that reports a perfectly sensible geometry and is simply
never drawn. `_strip_chrome()` defers it and re-asserts position afterwards.
Tk's `::tk::unsupported::MacWindowStyle` is the other documented route; it
reports success on current macOS and leaves the title bar in place, so it
isn't used. If `overrideredirect()` ever fails the app keeps its title bar
rather than refusing to start.

The macOS side of PWM-safe mode uses `CoreDisplay`, an undocumented private
framework (the same one tools like the `brightness` CLI rely on, since
Apple's public IOKit brightness API stopped working for the internal panel
on Apple Silicon). Private frameworks move or stop working across macOS
versions without notice, and this one has: on macOS 26 the write call
raises nothing, returns success, and changes nothing at all.

There is no error to catch, so `enable_pwm_safe()` proves the backlight is
drivable rather than assuming it. It nudges the brightness by 5% and reads
it back; if it didn't move, the mode refuses to engage and the panel says
"can't control this backlight". The nudge is deliberately *away* from where
the backlight already sits — an earlier version only verified when the
backlight started below 98%, so on a display already at full, setting it to
full again "succeeded" and a completely dead write path passed for a working
PWM-safe mode.

`hold_pwm_safe()` re-asserts the lock on the app's 30-second tick, because
"locked to 100%" was otherwise only true for the instant the switch was
flipped. If the backlight slips and can't be put back, the switch turns
itself off with "lost control of backlight" rather than continuing to claim
a lock it doesn't have.

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
