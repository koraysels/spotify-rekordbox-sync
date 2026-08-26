#!/usr/bin/env bash
# Set the version in every place that carries one.
#
# CI stamps the version from the git tag, but only inside the runner — that
# change is never committed. Without running this first, a local build reports
# whatever version was last committed, which drifts behind the releases and
# makes "which build is this?" unanswerable.
set -euo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
  echo "usage: $0 <version>   e.g. $0 0.2.0" >&2
  exit 2
fi
if ! printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "version must look like 1.2.3 (no leading v)" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$VERSION" "$ROOT" <<'PY'
import json, pathlib, re, sys

version, root = sys.argv[1], pathlib.Path(sys.argv[2])

conf = root / "ui" / "src-tauri" / "tauri.conf.json"
data = json.loads(conf.read_text())
data["version"] = version
conf.write_text(json.dumps(data, indent=2) + "\n")

for toml in (root / "ui" / "src-tauri" / "Cargo.toml", root / "core" / "pyproject.toml"):
    toml.write_text(
        re.sub(r'^version = ".*"$', f'version = "{version}"',
               toml.read_text(), count=1, flags=re.M)
    )
print(f"set version to {version}")
PY

echo "next: git commit -am \"chore: version $VERSION\" && git tag v$VERSION && git push origin main v$VERSION"
