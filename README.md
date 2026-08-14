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
- **Zero blue, zero flicker** — one switch for the two things that make a
  screen hurt, done as hard as software can do them. The blue ramp is written
  as literal zeros (not "very warm", not 1900K — zero), the temperature is
  pinned to the warmest end so green comes down the blackbody curve with it
  and the result reads as candle-amber rather than sickly green, and the
  backlight is locked to 100% so nothing is strobing while the dimming
  happens in the ramp. The warmth slider and presets grey out while it's on,
  because the ramp is ignoring them and a preset that silently does nothing
  is worse than a preset you can't click.

  The two halves fail separately, so the line under the switch says which
  one you're actually getting: *"no blue, backlight steady"* when both are
  in force, *"no blue — can't hold this backlight"* when only the colour
  half is. Switching the mode off puts back the warmth and the backlight
  setting you had before it — including across a restart, since the
  displaced values are saved alongside the mode.

  **What "zero blue" honestly means.** Zero blue *out of the gamma ramp*,
  which is the whole of what any software on any OS controls. An LCD
  backlight is a blue LED behind a phosphor, and a little of that blue leaks
  through the red and green subpixel filters no matter what the GPU sends.
  Removing the rest is a job for the panel, not for this app.
- **No-flicker dimming** — the backlight half of the mode above, on its own
  switch for anyone who wants a flicker-free backlight without the amber.
  Most screens dim by switching the backlight fully
  on and off hundreds of times a second (pulse-width modulation). Your eye
  averages it into "dimmer"; a minority get headaches and eye strain from it,
  worst at low brightness. This holds the backlight at 100%, where there is
  no flicker because the LED never switches off, and does all the dimming in
  software through the gamma ramp instead. It re-asserts that every 30
  seconds, so the brightness keys or auto-brightness can't quietly put you
  back into flickering while the switch still claims to be on. Only the
  primary/built-in display is supported (external monitors need DDC/CI, which
  isn't wired up).

  **The option is only shown when the backlight can actually be driven.** On
  startup the app nudges the brightness 5% and reads it back; if nothing
  moves, the row isn't built at all rather than offering a switch that could
  only ever refuse. This used to hide the row on every current Mac, because
  the app drove the backlight through `CoreDisplay`, which stopped working
  somewhere before macOS 26. It now goes through `DisplayServices` first and
  the row appears again — see the internals section for what changed.

  It was called "PWM-safe mode". The acronym meant nothing to anyone who
  hadn't already researched the problem, which is precisely the audience the
  feature exists for.
- **The menu-bar icon shows the state** — amber while the app is easing the
  screen, blue while it isn't. Blue is the light that reaches you when
  nothing is filtering it, so the icon says what's happening to your screen
  rather than which switch was pressed last. The EASE button in the panel
  goes the same two colours.

  Blue is otherwise a colour this app can't use: the gamma ramp takes the
  blue channel to zero at deep warmth, so a blue accent would darken into an
  unreadable smudge exactly when the app is working hardest (see the note at
  the top of `brand.py`). It's safe *here* and nowhere else, because blue is
  the off state, and off means the ramp has been reset — the colour is only
  ever drawn on an untouched screen.

  The bundle icon in Finder and the Dock stays amber. That one is the app's
  identity rather than its state; it's mostly seen when the app isn't
  running, so there'd be no state for it to report.
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

The macOS side of no-flicker dimming drives the backlight through private
frameworks, because Apple's public IOKit brightness API stopped working for
the internal panel on Apple Silicon. Private frameworks move or stop working
across macOS versions without notice, and the one this app started on has:
measured on a MacBook Air (M4, macOS 26.5.2), `CoreDisplay`'s write call
raises nothing, returns success and moves nothing, while its read reports a
flat 1.0 with the panel plainly sitting at 45%. Both symbols still resolve,
so nothing errors and nothing works.

`DisplayServices` drives the same panel correctly on that machine, so it is
tried first, with `CoreDisplay` kept underneath for older Macs where the
reverse is true. Neither is trusted on its word — the probe below is what
decides.

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

### The one Windows thing most likely to bite
Windows sanity-checks gamma ramps and refuses any it considers too far from
linear. The warmest settings here drive blue to zero across the entire ramp,
which is exactly the shape it objects to, so **the deep end of the warmth
slider may do nothing on a stock Windows install** while the mild end works
fine.

`SetDeviceGammaRamp` reports this by returning false rather than raising, so
the refusal is completely silent unless you check — which is why `apply()`
now returns a bool and the panel shows "your system refused the colour
change" rather than leaving you with a slider that moves and a screen that
doesn't.

The documented fix is a machine-wide registry value that widens the allowed
range (Redshift and f.lux both depend on it):

```
HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ICM\GdiIcmGammaRange = 256  (DWORD)
```

This app deliberately does not write it. It needs admin rights, it affects
every program on the machine, and silently changing a system-wide graphics
setting is not something a screen dimmer should do behind your back.

### What to check on a real Windows machine
None of the below has ever been run. In rough order of how likely it is to
be broken:

1. **Warmth at the deep end** — drag to the warmest setting. If the screen
   doesn't change and the panel shows the refusal message, that's the gamma
   range limit above, not a crash.
2. **PWM-safe mode** — Windows exposes only the discrete brightness levels a
   panel supports, so the writability probe checks the backlight *moved*
   rather than landed exactly where asked. Watch for it wrongly reporting
   "can't control this backlight" on a laptop where the brightness keys work.
3. **Launch at login** — should add a value under
   `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. Check the app
   actually starts after a reboot, not just that the value exists.
4. **The borderless panel** — `overrideredirect()` behaves differently on
   Windows; if the panel can't be dragged or won't come back from the tray,
   that's the place to look.
5. **Desktop/external monitors** — `WmiMonitorBrightness` generally doesn't
   exist for them, so PWM-safe should decline rather than error.
