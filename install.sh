#!/usr/bin/env bash
# Install rbsync into /Applications and clear the macOS quarantine flag.
#
# The app is not signed with an Apple Developer ID, so macOS quarantines it and
# reports "rbsync is damaged and can't be opened". That message is about the
# missing signature, not a corrupt download. Removing the quarantine attribute
# is the supported way to run an unsigned app you trust.
set -euo pipefail

APP_NAME="rbsync.app"
TARGET="/Applications/$APP_NAME"

find_source() {
  # Prefer a locally built bundle, fall back to a mounted DMG.
  local here built
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  built="$here/ui/src-tauri/target/release/bundle/macos/$APP_NAME"
  if [ -d "$built" ]; then
    echo "$built"
    return 0
  fi
  for volume in /Volumes/*/"$APP_NAME"; do
    if [ -d "$volume" ]; then
      echo "$volume"
      return 0
    fi
  done
  return 1
}

SOURCE="$(find_source)" || {
  echo "Could not find $APP_NAME."
  echo "Build it first:  ./core/build_sidecar.sh && npm --prefix ui run tauri build"
  echo "Or mount the .dmg and run this again."
  exit 1
}

echo "Installing from: $SOURCE"

if [ -d "$TARGET" ]; then
  echo "Replacing existing $TARGET"
  rm -rf "$TARGET"
fi

cp -R "$SOURCE" "$TARGET"

# Strip the quarantine flag from the bundle and the embedded sidecar binary.
xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null || true

# Re-sign ad-hoc. Tauri's own ad-hoc signature can end up without a resource
# seal ("code has no resources but signature indicates they must be present"),
# and macOS then kills the app and its sidecar on launch — which looks like
# "the app is damaged" and like the app hanging forever. Signing here produces
# a valid seal. It is still not a Developer ID signature.
if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$TARGET" >/dev/null 2>&1 || true
  if codesign --verify --deep --strict "$TARGET" >/dev/null 2>&1; then
    echo "signature: valid (ad-hoc)"
  else
    echo "signature: still invalid — the app may refuse to launch" >&2
  fi
fi

echo
echo "Installed: $TARGET"
echo "Open it from Applications, or run: open '$TARGET'"
