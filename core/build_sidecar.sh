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
