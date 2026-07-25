# Tap Zap Lite

Free, minimal blue-light blocker for Mac and Windows — same idea as RedShift
(gamma-table manipulation), styled after Tap Zap: two sliders, three presets,
one ZAP button, lives in the tray.

## How it works, in one paragraph
Every screen redraws pixels through a "gamma ramp" — a lookup table that maps
input color to output color for red, green, and blue separately. This app
bends the green/blue curves downward so those colors get dimmer no matter
what's on screen, while brightness scales all three curves together as a
software dim. `gamma.py` has the full explanation inline.

## Run it
```
pip install -r requirements.txt
python main.py
```

A small panel appears with:
- **Warmth slider** — 0 (screen unchanged) to 1 (blue/green removed, pure red)
- **Brightness slider** — software dim, 0.15 to 1.0
- **Three presets** — Reading, Evening, Sleep
- **⚡ button** — on/off, screen reverts instantly when off
- Closing the panel just hides it to the tray icon; use Quit from the tray
  menu to fully exit (this also resets your screen automatically)

Settings are saved to `~/.tapzaplite_settings.json` and restored next launch.

## What's deliberately left out of this version
Tap Zap's other headline feature is **PWM-safe mode** — locking your physical
backlight at 100% and dimming in software instead, so the screen's own
flicker never engages. That requires per-monitor hardware brightness control
(DDC/CI on Windows, a different macOS API for external displays) and is a
good "v2" project once this base version feels solid.

Multi-monitor support is also stubbed out but not wired up yet — notes on
exactly where to add it are inline in `gamma.py`.

## Packaging into a real .app / .exe
Once this works from source, use PyInstaller (same tool RedShift's
`build_release.py` uses) to produce a double-clickable app. Ask me when
you're ready for that step — it's a separate script, not something to
bolt on here.
