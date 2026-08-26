"""Local persistence: match decisions, playlist selection, sync history, settings.

This is intentionally plain ``sqlite3`` rather than an ORM. The schema is four
small tables, and the sidecar already carries SQLAlchemy for rekordbox; adding
a second mapped layer here would buy nothing.

The decision table is what makes review tolerable: an ambiguous track is judged
once and never asked about again, so the first sync of a large library is the
only one that involves clicking.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 3


@dataclass(frozen=True, slots=True)
class Decision:
    spotify_id: str
    content_id: str
    accepted: bool
    decided_at: str


@dataclass(frozen=True, slots=True)
class StoredPlan:
    playlist_id: str
    snapshot_id: str
    fingerprint: str
    payload: dict
    created_at: str


@dataclass(frozen=True, slots=True)
class SyncEntry:
    playlist_id: str
    added: int
    removed: int
    matched: int
    total: int
    synced_at: str
    playlist_name: str = ""
    backup_path: str = ""

    @property
    def coverage_percent(self) -> float:
        if self.total == 0:
            return 0.0
        return round(100.0 * self.matched / self.total, 1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Cache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The dev HTTP bridge serves requests on multiple threads, so the
        # connection is shared rather than bound to its creating thread. Every
        # statement is serialised through _lock to keep that safe.
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._db.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        self._create_schema()
        if version < 2:
            self._add_history_columns()
        self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._db.commit()

    def _add_history_columns(self) -> None:
        """Version 2 records which playlist and which backup a sync belonged to.

        Older rows keep their data and read the new columns as empty rather than
        being dropped and recreated.
        """
        existing = {
            row["name"] for row in self._db.execute("PRAGMA table_info(sync_history)")
        }
        for column in ("playlist_name", "backup_path"):
            if column not in existing:
                self._db.execute(
                    f"ALTER TABLE sync_history ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                )

    def _create_schema(self) -> None:
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
                synced_at   TEXT NOT NULL,
                playlist_name TEXT NOT NULL DEFAULT '',
                backup_path   TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_sync_playlist ON sync_history(playlist_id, id DESC);
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plans (
                playlist_id TEXT PRIMARY KEY,
                snapshot_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                payload     TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );
            """
        )

    # --- decisions ---------------------------------------------------------

    def remember_decision(self, spotify_id: str, content_id: str, accepted: bool) -> None:
        """Record a human judgement so it is never asked again.

        Rejections are stored explicitly. Treating "no row" and "rejected" as
        the same thing would re-propose a match the user already turned down.
        """
        with self._lock:
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
        with self._lock:
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

    def decisions_marker(self) -> str:
        """A value that changes whenever any decision is added or altered.

        Used to invalidate stored plans: a plan computed before the user
        accepted or rejected a match no longer reflects what would be written.
        """
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS n, COALESCE(MAX(decided_at), '') AS latest FROM decisions"
            ).fetchone()
        return f"{row['n']}:{row['latest']}"

    def forget_decision(self, spotify_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM decisions WHERE spotify_id = ?", (spotify_id,))
            self._db.commit()

    # --- selection ---------------------------------------------------------

    def set_selected_playlists(self, playlist_ids: list[str]) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM selection")
            self._db.executemany(
                "INSERT OR IGNORE INTO selection (playlist_id) VALUES (?)",
                [(pid,) for pid in playlist_ids],
            )

    def get_selected_playlists(self) -> list[str]:
        with self._lock:
            rows = self._db.execute("SELECT playlist_id FROM selection").fetchall()
        return [r["playlist_id"] for r in rows]

    # --- history -----------------------------------------------------------

    def record_sync(
        self,
        playlist_id: str,
        *,
        added: int,
        removed: int,
        matched: int,
        total: int,
        playlist_name: str = "",
        backup_path: str = "",
    ) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO sync_history
                    (playlist_id, added, removed, matched, total, synced_at,
                     playlist_name, backup_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (playlist_id, added, removed, matched, total, _now(),
                 playlist_name, backup_path),
            )
            self._db.commit()

    def get_history(self, playlist_id: str | None = None, limit: int = 50) -> list[SyncEntry]:
        """Past syncs, newest first.

        Kept so the user can answer "what did this thing actually do to my
        library, and which backup goes with it" long after the fact.
        """
        with self._lock:
            if playlist_id:
                rows = self._db.execute(
                    "SELECT * FROM sync_history WHERE playlist_id = ? ORDER BY id DESC LIMIT ?",
                    (playlist_id, limit),
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM sync_history ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._entry(row) for row in rows]

    @staticmethod
    def _entry(row) -> SyncEntry:
        keys = row.keys()
        return SyncEntry(
            playlist_id=row["playlist_id"],
            added=row["added"],
            removed=row["removed"],
            matched=row["matched"],
            total=row["total"],
            synced_at=row["synced_at"],
            playlist_name=row["playlist_name"] if "playlist_name" in keys else "",
            backup_path=row["backup_path"] if "backup_path" in keys else "",
        )

    def get_last_sync(self, playlist_id: str) -> SyncEntry | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM sync_history WHERE playlist_id = ? ORDER BY id DESC LIMIT 1",
                (playlist_id,),
            ).fetchone()
        if row is None:
            return None
        return self._entry(row)

    # --- plans -------------------------------------------------------------

    def save_plan(self, playlist_id: str, *, snapshot_id: str, fingerprint: str,
                  payload: dict) -> None:
        """Store a computed plan so the next launch does not have to redo it."""
        with self._lock:
            self._db.execute(
                """
                INSERT INTO plans (playlist_id, snapshot_id, fingerprint, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(playlist_id) DO UPDATE SET
                    snapshot_id = excluded.snapshot_id,
                    fingerprint = excluded.fingerprint,
                    payload     = excluded.payload,
                    created_at  = excluded.created_at
                """,
                (playlist_id, snapshot_id, fingerprint, json.dumps(payload), _now()),
            )
            self._db.commit()

    def get_plan(self, playlist_id: str) -> StoredPlan | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM plans WHERE playlist_id = ?", (playlist_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload"])
        except ValueError:
            # A corrupt payload is not worth crashing over; treat it as absent.
            return None
        return StoredPlan(
            playlist_id=row["playlist_id"],
            snapshot_id=row["snapshot_id"],
            fingerprint=row["fingerprint"],
            payload=payload,
            created_at=row["created_at"],
        )

    def delete_plan(self, playlist_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM plans WHERE playlist_id = ?", (playlist_id,))
            self._db.commit()

    def clear_plans(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM plans")
            self._db.commit()

    # --- playlist list -----------------------------------------------------

    def save_playlists(self, payload: list[dict]) -> None:
        """Remember the playlist list purely so the UI can paint immediately.

        This is never the basis for a sync: a live fetch always follows and
        replaces it.
        """
        self.set_setting("playlists_cache", json.dumps(payload))

    def get_playlists(self) -> list[dict]:
        raw = self.get_setting("playlists_cache", "")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except ValueError:
            return []
        return data if isinstance(data, list) else []

    # --- settings ----------------------------------------------------------

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._db.commit()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
