# Contributing to EyeEase

Thanks for considering it. This is a small project, so the process is small too.

## Setup
Follow the **Setup** and **Run it** sections in the [README](README.md). If you
hit the Xcode-stub-Python blank-window issue, that's documented there too —
it's not you.

## Where to start
Two concrete, scoped-out tasks are already called out in the README's
["What's deliberately left out"](README.md#whats-deliberately-left-out-of-this-version)
section:

- **Multi-monitor gamma support** — loop over `CGGetActiveDisplayList()` on
  macOS and call `SetDeviceGammaRamp` per monitor on Windows, instead of just
  the primary display. Notes on exactly where this goes are inline in
  `gamma.py`.
- **DDC/CI for external monitors** — extend PWM-safe mode past the built-in
  panel. Neither macOS nor Windows has a built-in API for this, so it'll need
  a DDC/CI library.

Found something else worth fixing? Open an issue first for anything beyond a
small fix, so we're aligned before you put time into it.

## Submitting changes
1. Fork the repo, make your change on a branch.
2. Test it by actually running the app (`python3 main.py`) — this is a UI/
   hardware-interaction tool, not something unit tests can fully cover.
3. Open a PR with a short description of what changed and why.

## Style
Match what's already there: plain functions over classes where possible,
comments that explain *why* (a gotcha, a platform quirk) rather than *what*
the code does.
