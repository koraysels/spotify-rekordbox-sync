"""Frozen-binary entry point.

PyInstaller runs the entry script as a top-level ``__main__`` with no package
context, so ``rbsync/__main__.py``'s relative imports cannot be used here.
This module imports absolutely and is the script PyInstaller freezes.
"""

from __future__ import annotations

import logging
import sys

from rbsync.api import build_server


def main() -> int:
    # stdout is the RPC channel; everything else must go to stderr.
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    build_server().serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
