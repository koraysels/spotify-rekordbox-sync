"""Local persistence: match decisions, playlist selection, sync history, settings.

This is intentionally plain ``sqlite3`` rather than an ORM. The schema is four
small tables, and the sidecar already carries SQLAlchemy for rekordbox; adding
a second mapped layer here would buy nothing.

The decision table is what makes review tolerable: an ambiguous track is judged
once and never asked about again, so the first sync of a large library is the
only one that involves clicking.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Decision:
    spotify_id: str
    content_id: str
    accepted: bool
    decided_at: str


@dataclass(frozen=True, slots=True)
class SyncEntry:
    playlist_id: str
    added: int
    removed: int
    matched: int
    total: int
    synced_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Cache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path))
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                spotify_id TEXT PRIMARY KEY,
                content_id TEXT NOT NULL,
                accepted   INTEGER NOT NULL,
                decided_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS selection (
                playlist_id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS sync_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id TEXT NOT NULL,
                added       INTEGER NOT NULL,
                removed     INTEGER NOT NULL,
                matched     INTEGER NOT NULL,
                total       INTEGER NOT NULL,
                synced_at   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sync_playlist ON sync_history(playlist_id, id DESC);
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._db.commit()

    # --- decisions ---------------------------------------------------------

    def remember_decision(self, spotify_id: str, content_id: str, accepted: bool) -> None:
        """Record a human judgement so it is never asked again.

        Rejections are stored explicitly. Treating "no row" and "rejected" as
        the same thing would re-propose a match the user already turned down.
        """
        self._db.execute(
            """
            INSERT INTO decisions (spotify_id, content_id, accepted, decided_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(spotify_id) DO UPDATE SET
                content_id = excluded.content_id,
                accepted   = excluded.accepted,
                decided_at = excluded.decided_at
            """,
            (spotify_id, content_id, 1 if accepted else 0, _now()),
        )
        self._db.commit()

    def get_decision(self, spotify_id: str) -> Decision | None:
        row = self._db.execute(
            "SELECT * FROM decisions WHERE spotify_id = ?", (spotify_id,)
        ).fetchone()
        if row is None:
            return None
        return Decision(
            spotify_id=row["spotify_id"],
            content_id=row["content_id"],
            accepted=bool(row["accepted"]),
            decided_at=row["decided_at"],
        )

    def forget_decision(self, spotify_id: str) -> None:
        self._db.execute("DELETE FROM decisions WHERE spotify_id = ?", (spotify_id,))
        self._db.commit()

    # --- selection ---------------------------------------------------------

    def set_selected_playlists(self, playlist_ids: list[str]) -> None:
        with self._db:
            self._db.execute("DELETE FROM selection")
            self._db.executemany(
                "INSERT OR IGNORE INTO selection (playlist_id) VALUES (?)",
                [(pid,) for pid in playlist_ids],
            )

    def get_selected_playlists(self) -> list[str]:
        rows = self._db.execute("SELECT playlist_id FROM selection").fetchall()
        return [r["playlist_id"] for r in rows]

    # --- history -----------------------------------------------------------

    def record_sync(
        self, playlist_id: str, *, added: int, removed: int, matched: int, total: int
    ) -> None:
        self._db.execute(
            """
            INSERT INTO sync_history (playlist_id, added, removed, matched, total, synced_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (playlist_id, added, removed, matched, total, _now()),
        )
        self._db.commit()

    def get_last_sync(self, playlist_id: str) -> SyncEntry | None:
        row = self._db.execute(
            "SELECT * FROM sync_history WHERE playlist_id = ? ORDER BY id DESC LIMIT 1",
            (playlist_id,),
        ).fetchone()
        if row is None:
            return None
        return SyncEntry(
            playlist_id=row["playlist_id"],
            added=row["added"],
            removed=row["removed"],
            matched=row["matched"],
            total=row["total"],
            synced_at=row["synced_at"],
        )

    # --- settings ----------------------------------------------------------

    def set_setting(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._db.commit()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
