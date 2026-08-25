#!/usr/bin/env bash
# Freeze the Python core into a single binary and place it where Tauri expects
# its sidecar. Tauri resolves sidecars by target triple, so the suffix matters.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
VENV="$HERE/.venv"
TRIPLE="$(rustc -Vv | awk '/^host:/ {print $2}')"
OUT_DIR="$ROOT/ui/src-tauri/binaries"

if [ ! -x "$VENV/bin/python" ]; then
  echo "creating virtualenv"
  uv venv "$VENV" --python 3.12
fi

uv pip install --python "$VENV/bin/python" -q -e "$HERE" pyinstaller

cd "$HERE"

# Bake the bundled Spotify Client ID into the frozen core, so the shipped app
# can sign in with one click. A Client ID is public information under PKCE;
# no secret is embedded. Restored afterwards so the working tree stays clean.
BRANDING="$HERE/rbsync/branding.py"
BRANDING_BACKUP="$(mktemp)"
cp "$BRANDING" "$BRANDING_BACKUP"
restore_branding() { cp "$BRANDING_BACKUP" "$BRANDING"; rm -f "$BRANDING_BACKUP"; }
trap restore_branding EXIT

if [ -n "${RBSYNC_SPOTIFY_CLIENT_ID:-}" ]; then
  python3 - "$BRANDING" "$RBSYNC_SPOTIFY_CLIENT_ID" <<'PYEOF'
import sys, pathlib
path, client_id = pathlib.Path(sys.argv[1]), sys.argv[2]
text = path.read_text()
text = text.replace('DEFAULT_SPOTIFY_CLIENT_ID = ""',
                    f'DEFAULT_SPOTIFY_CLIENT_ID = "{client_id}"')
path.write_text(text)
PYEOF
  echo "bundled Spotify Client ID: ${RBSYNC_SPOTIFY_CLIENT_ID:0:6}..."
else
  echo "no RBSYNC_SPOTIFY_CLIENT_ID set - users must supply their own Client ID"
fi

"$VENV/bin/pyinstaller" \
  --noconfirm --clean --onefile \
  --name rbsync-core \
  --distpath "$HERE/dist" \
  --workpath "$HERE/build" \
  --specpath "$HERE/build" \
  --collect-all pyrekordbox \
  --collect-all sqlcipher3 \
  --hidden-import sqlcipher3 \
  --hidden-import rbsync.api \
  sidecar.py

mkdir -p "$OUT_DIR"
cp "$HERE/dist/rbsync-core" "$OUT_DIR/rbsync-core-$TRIPLE"
chmod +x "$OUT_DIR/rbsync-core-$TRIPLE"
echo "sidecar ready: $OUT_DIR/rbsync-core-$TRIPLE"
