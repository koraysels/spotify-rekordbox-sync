"""Sidecar entry point: ``python -m rbsync`` speaks JSON-RPC on stdio."""

from __future__ import annotations

import logging
import sys

from .api import build_server


def main() -> int:
    # Logs go to stderr; stdout is the RPC channel and must stay clean.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(levelname)s %(name)s: %(message)s")
    build_server().serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
