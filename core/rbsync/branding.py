"""Build-time identity for the shipped application.

A Spotify **Client ID is not a secret** — the PKCE flow exists precisely so
public clients can authenticate without one, and the id is visible in the
authorize URL of every desktop and mobile app. Baking it into the build is
therefore safe, and it is what turns sign-in into a single button instead of a
setup chore.

``build_sidecar.sh`` rewrites the value below from ``$RBSYNC_SPOTIFY_CLIENT_ID``
at package time. A user-supplied Client ID in settings always wins, so anyone
who prefers their own app can still use it.
"""

from __future__ import annotations

import os

# Replaced at build time. Empty means "no bundled app; user must supply one".
DEFAULT_SPOTIFY_CLIENT_ID = ""


def default_client_id() -> str:
    """The bundled Client ID, if this build has one."""
    return (os.environ.get("RBSYNC_SPOTIFY_CLIENT_ID") or DEFAULT_SPOTIFY_CLIENT_ID).strip()
