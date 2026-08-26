#!/usr/bin/env bash
# Build the desktop app: freeze the Python core, then bundle it with Tauri.
#
# The updater needs its signing key. CI supplies it from repository secrets;
# locally it lives at ~/.rbsync/updater.key, outside the repo so it can never be
# committed. Without a key Tauri fails after bundling ("a public key has been
# found, but no private key"), so this checks up front and says what to do.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEY_FILE="${RBSYNC_UPDATER_KEY:-$HOME/.rbsync/updater.key}"

if [ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]; then
  if [ -f "$KEY_FILE" ]; then
    TAURI_SIGNING_PRIVATE_KEY="$(cat "$KEY_FILE")"
    export TAURI_SIGNING_PRIVATE_KEY
    export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}"
    echo "updater key: $KEY_FILE"
  else
    echo "No updater signing key found at $KEY_FILE." >&2
    echo "Generate one with:  npm --prefix ui exec -- tauri signer generate -w $KEY_FILE" >&2
    echo "then add the public key to ui/src-tauri/tauri.conf.json." >&2
    exit 1
  fi
fi

"$ROOT/core/build_sidecar.sh"
npm --prefix "$ROOT/ui" run tauri build
