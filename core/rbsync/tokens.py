"""Persistence for Spotify tokens.

Stored as a file with owner-only permissions. The Tauri shell is the intended
home for these (macOS Keychain / Windows Credential Manager), and the shell can
inject them through ``auth.setTokens``; this file backend is what makes the
Python core usable on its own from the CLI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .spotify import Tokens


class TokenStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> Tokens | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text())
            return Tokens(
                access_token=payload["access_token"],
                refresh_token=payload.get("refresh_token", ""),
                expires_at=float(payload.get("expires_at", 0)),
            )
        except (ValueError, KeyError, OSError):
            return None

    def save(self, tokens: Tokens) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(tokens.as_dict(), indent=2))
        # Tokens grant access to the user's Spotify account; keep them
        # readable only by the account that owns them.
        os.chmod(self.path, 0o600)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
