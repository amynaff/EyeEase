#!/bin/bash
#
# release.sh — build, sign, notarise, staple, and verify a distributable app.
#
# Without this, macOS tells everyone who downloads EyeEase that Apple could
# not verify it is free of malware. That warning costs more users than any
# missing feature will.
#
# Needs two things, neither of which lives in this repo:
#
#   1. A "Developer ID Application" certificate in your keychain. Note the
#      type — an "Apple Development" certificate is for running on your own
#      devices and Apple will refuse to notarise anything signed with it.
#      Create it at developer.apple.com → Certificates → + → Developer ID
#      Application, download, and double-click to install.
#
#   2. A notarytool credential profile, stored in your keychain by you:
#
#        xcrun notarytool store-credentials "eyeease" \
#          --apple-id "you@example.com" \
#          --team-id "YOURTEAMID" \
#          --password "app-specific-password"
#
#      Generate the app-specific password at appleid.apple.com → Sign-In and
#      Security → App-Specific Passwords. It is a real credential: it goes
#      into your keychain via the command above and nowhere else. Never put
#      it in a file in this repository.
#
# Then:  ./release.sh
#
set -euo pipefail

PROFILE="${EYEEASE_NOTARY_PROFILE:-eyeease}"
VENV="./.venv/bin"

echo "==> Checking for a Developer ID Application certificate"
# The `|| true` matters: no matching certificate makes grep exit non-zero,
# and under `set -o pipefail` that aborts the script here — swallowing the
# explanation below at exactly the moment someone needs to read it.
IDENTITY="$(security find-identity -v -p codesigning \
  | grep "Developer ID Application" \
  | head -1 \
  | sed -E 's/.*"(.*)"/\1/' || true)"

if [ -z "$IDENTITY" ]; then
  echo
  echo "No 'Developer ID Application' certificate found in your keychain."
  echo
  security find-identity -v -p codesigning | sed 's/[A-F0-9]\{40\}/<hash>/' || true
  echo
  echo "An 'Apple Development' certificate is not a substitute — it signs"
  echo "apps for your own devices and Apple will reject it for notarising."
  echo "Create a Developer ID Application certificate at developer.apple.com,"
  echo "download it, double-click to install, then run this again."
  exit 1
fi
echo "    $IDENTITY"

echo "==> Checking the version label matches everywhere"
# version.py is the source of truth, but two other files state the version in
# prose, and prose doesn't import anything. Both have drifted before — the
# site advertised a version that had already been superseded — and the drift
# is only ever noticed after the release is out. Checking here costs nothing
# and turns a silent wrong number into a stop.
# Read as text, not via `import version`. Importing goes through Python's
# bytecode cache, and a stale .pyc is served without complaint — which is
# exactly the class of silent-wrong-value this check exists to catch. A
# check that can itself be fed a stale answer is worse than no check.
VERSION="$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' version.py)"
if [ -z "$VERSION" ]; then
  echo "    couldn't read APP_VERSION out of version.py"
  exit 1
fi
echo "    version.py says $VERSION"
for f in README.md website/index.html; do
  if ! grep -q "v$VERSION" "$f"; then
    echo
    echo "$f does not mention v$VERSION."
    echo "Found instead:"
    grep -oE "v[0-9]+\.[0-9]+\.[0-9]+" "$f" | sort -u | sed 's/^/    /' || echo "    (no version at all)"
    echo
    echo "Bump it to match version.py, then run this again."
    exit 1
  fi
  echo "    $f mentions v$VERSION"
done

echo "==> Building"
# __pycache__ as well as build/dist: eyeease.spec imports version.py to set
# CFBundleShortVersionString, and a stale .pyc there would stamp the bundle
# with a version that isn't the one in the file.
rm -rf build dist __pycache__
EYEEASE_CODESIGN_IDENTITY="$IDENTITY" "$VENV/pyinstaller" --noconfirm eyeease.spec >/dev/null
echo "    dist/EyeEase.app"

echo "==> Verifying the signature and the hardened runtime"
codesign --verify --deep --strict --verbose=2 dist/EyeEase.app
# Notarisation is refused without the hardened runtime, and the failure
# arrives minutes later from Apple rather than here, so check it now.
#
# Captured into a variable rather than piped into `grep -q`. Under
# `set -o pipefail` that pipe is a race: grep -q exits at the first match,
# codesign then dies of SIGPIPE, and the pipeline reports failure — but only
# when codesign hadn't finished writing yet. It passed and failed on
# alternating runs against an identical, correctly signed app.
SIGNATURE="$(codesign -d --verbose=2 dist/EyeEase.app 2>&1)"
case "$SIGNATURE" in
  *"(runtime"*) ;;
  *)
    echo "    the hardened runtime is not enabled — notarisation would be rejected"
    echo "$SIGNATURE" | grep -i flags || true
    exit 1
    ;;
esac
echo "    signed, hardened runtime on"

echo "==> Zipping for submission"
# ditto, not zip: a .app is a bundle of symlinks and metadata that plain zip
# quietly mangles, and the result fails to launch on someone else's machine.
( cd dist && ditto -c -k --keepParent --sequesterRsrc EyeEase.app EyeEase-macOS.zip )

echo "==> Submitting to Apple (this usually takes a few minutes)"
if ! xcrun notarytool submit dist/EyeEase-macOS.zip \
      --keychain-profile "$PROFILE" --wait; then
  echo
  echo "Notarisation failed. For the reason:"
  echo "  xcrun notarytool history --keychain-profile \"$PROFILE\""
  echo "  xcrun notarytool log <submission-id> --keychain-profile \"$PROFILE\""
  exit 1
fi

echo "==> Stapling the ticket to the app"
# Stapling is what lets the app open on a machine that is offline; without it
# Gatekeeper has to reach Apple to confirm, and fails closed if it can't.
xcrun stapler staple dist/EyeEase.app

echo "==> Re-zipping, so the download contains the stapled app"
# The staple modifies the bundle, so the zip made before it is already stale.
rm -f dist/EyeEase-macOS.zip
( cd dist && ditto -c -k --keepParent --sequesterRsrc EyeEase.app EyeEase-macOS.zip )

echo "==> Final check: what Gatekeeper will say to someone who downloads this"
xcrun stapler validate dist/EyeEase.app
spctl --assess --type execute --verbose=4 dist/EyeEase.app

echo
echo "Done. dist/EyeEase-macOS.zip is ready to upload:"
echo "  gh release upload v$("$VENV/python" -c 'import version; print(version.APP_VERSION)') dist/EyeEase-macOS.zip --repo amynaff/EyeEase --clobber"
