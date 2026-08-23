"""version.py — the one place the version string lives.

eyeease.spec (itself a Python script PyInstaller executes) imports this so
the built bundle's CFBundleShortVersionString can't drift from what the
running app thinks its own version is — which is exactly the drift that
made the website's version label wrong the last time this got bumped by
hand in two places instead of one.
"""

APP_VERSION = "0.2.1"
