# EyeEase

Free, minimal blue-light blocker for Mac and Windows — same idea as RedShift
(gamma-table manipulation), styled after Tap Zap: two sliders, three presets,
one ZAP button, lives in the tray.

## How it works, in one paragraph
Every screen redraws pixels through a "gamma ramp" — a lookup table that maps
input color to output color for red, green, and blue separately. This app
bends the green/blue curves downward so those colors get dimmer no matter
what's on screen, while brightness scales all three curves together as a
software dim. `gamma.py` has the full explanation inline.

## Setup
Requires Python 3.9+.

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
- **Warmth slider** — 0 (screen unchanged) to 1 (blue/green removed, pure red)
- **Brightness slider** — software dim, 0.15 to 1.0
- **Three presets** — Reading, Evening, Sleep
- **PWM-safe mode switch** — locks the built-in display's physical backlight
  to 100% and restores it on quit, so all dimming happens through the gamma
  ramp instead of the backlight's own PWM. Only the primary/built-in display
  is supported (external monitors need DDC/CI, which isn't wired up); if the
  OS won't grant brightness access the switch snaps back off instead of
  claiming to be active.
- **⚡ button** — on/off, screen reverts instantly when off
- Closing the panel just hides it to the tray icon; use Quit from the tray
  menu to fully exit (this also resets your screen automatically)

Settings are saved to `~/.eyeease_settings.json` and restored next launch.

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
