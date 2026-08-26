#!/usr/bin/env python3
"""Build the Tauri updater manifest from the artifacts a release produced.

The updater fetches this file, compares versions, and downloads the platform
entry that matches. Each entry needs the signature Tauri produced at build time
— an update without a valid signature is refused, which is the point: an
auto-updater is a remote code execution channel into every install.

Only platforms that actually built get an entry. A missing Windows build should
mean "no Windows update yet", never a manifest pointing at a file that is not
there.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

# Tauri's platform keys, and how to recognise the artifact for each.
PLATFORMS = {
    "darwin-aarch64": lambda name: name.endswith(".app.tar.gz") and "darwin-aarch64" in name,
    "darwin-x86_64": lambda name: name.endswith(".app.tar.gz") and "darwin-x86_64" in name,
    "windows-x86_64": lambda name: name.endswith("-setup.exe") and "windows_x86_64" in name,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="release tag, e.g. v0.2.0")
    parser.add_argument("--artifacts", required=True, help="directory of downloaded artifacts")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--out", required=True)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    root = pathlib.Path(args.artifacts)
    files = {path.name: path for path in root.rglob("*") if path.is_file()}

    platforms: dict[str, dict[str, str]] = {}
    for key, matches in PLATFORMS.items():
        payload = next((name for name in files if matches(name)), None)
        if payload is None:
            print(f"  {key}: no artifact, skipping")
            continue

        signature_path = files.get(f"{payload}.sig")
        if signature_path is None:
            # Publishing an unsigned entry would make every client reject the
            # update anyway; saying so here is more useful than a silent hole.
            print(f"  {key}: {payload} has no .sig — skipping", file=sys.stderr)
            continue

        platforms[key] = {
            "signature": signature_path.read_text().strip(),
            "url": f"https://github.com/{args.repo}/releases/download/{args.tag}/{payload}",
        }
        print(f"  {key}: {payload}")

    if not platforms:
        print("no signed updater artifacts found; refusing to write a manifest", file=sys.stderr)
        return 1

    manifest = {
        "version": args.tag.lstrip("v"),
        "notes": args.notes or f"rbsync {args.tag}",
        "pub_date": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "platforms": platforms,
    }
    pathlib.Path(args.out).write_text(json.dumps(manifest, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
