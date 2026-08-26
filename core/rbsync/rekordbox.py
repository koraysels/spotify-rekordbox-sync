"""All rekordbox ``master.db`` access.

Every read and every write in this project goes through this module, and it is
the only place that imports pyrekordbox. That boundary exists because writing
to rekordbox's database is the highest-risk thing this application does:
the file is SQLCipher-encrypted, rekordbox maintains per-row update sequence
numbers that its own sync logic depends on, and a corrupted library is a real
loss for a DJ.

Three rules are enforced here rather than left to callers:

1. Rekordbox must not be running. Concurrent writers corrupt the database.
2. A verified backup is taken before any mutation.
3. Every mutation for one Apply commits as a single transaction, or rolls back.
"""

from __future__ import annotations

import logging
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import psutil
from pyrekordbox import Rekordbox6Database
from pyrekordbox.config import get_config

from .models import LocalTrack, RbPlaylist

log = logging.getLogger(__name__)

SPOTIFY_FOLDER = "Spotify"
BACKUP_PREFIX = "master_"
# The state of the library before this tool ever wrote to it. Kept apart from
# the rolling backups and never pruned: after ten syncs every rolling backup is
# itself post-rbsync, so without this there is nothing to go back to.
ORIGINAL_PREFIX = "original_"
BACKUP_KEEP = 10

# rekordbox runs SQLite in WAL mode, so recent commits live in these sidecars
# rather than in master.db. A backup of the main file alone can be hours stale,
# and a restore that leaves a newer -wal behind simply replays it.
SIDECARS = ("-wal", "-shm")

# Rekordbox marks folders with Attribute == 1; ordinary playlists use 0.
ATTR_PLAYLIST = 0
ATTR_FOLDER = 1


class RekordboxError(RuntimeError):
    """Base class for rekordbox access failures."""


class RekordboxRunning(RekordboxError):
    """Rekordbox is open, so writing would risk corrupting the library."""


class BackupFailed(RekordboxError):
    """A pre-write backup could not be produced or verified."""


class DatabaseNotFound(RekordboxError):
    """No rekordbox database could be located."""


def is_rekordbox_running() -> bool:
    """True if a rekordbox process is currently running.

    Matched on the process name rather than a bundle id so it works across
    macOS and Windows and across rekordbox 6 and 7.
    """
    for process in psutil.process_iter(["name"]):
        try:
            name = (process.info.get("name") or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "rekordbox" in name:
            return True
    return False


def default_database_path() -> Path:
    """Locate the installed rekordbox database."""
    for profile in ("rekordbox7", "rekordbox6"):
        try:
            path = get_config(profile, "db_path")
        except Exception:  # pragma: no cover - depends on local install
            continue
        if path and Path(path).exists():
            return Path(path)
    fallback = Path.home() / "Library" / "Pioneer" / "rekordbox" / "master.db"
    if fallback.exists():
        return fallback
    raise DatabaseNotFound("could not locate rekordbox master.db")


def backup_database(db_path: str | Path, backup_dir: str | Path) -> Path:
    """Copy the database aside and verify the copy before returning.

    Verification is not ceremony: a backup that silently truncated is worse
    than no backup, because it invites the user to trust it.
    """
    source = Path(db_path)
    if not source.exists():
        raise BackupFailed(f"database not found: {source}")

    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = _unique_backup_path(directory, BACKUP_PREFIX)

    _copy_database_set(source, target)

    if not target.exists():
        raise BackupFailed(f"backup was not created: {target}")
    expected = source.stat().st_size
    actual = target.stat().st_size
    if actual != expected:
        raise BackupFailed(
            f"backup size mismatch: expected {expected} bytes, got {actual}"
        )
    return target


def _copy_database_set(source: Path, target: Path) -> None:
    """Copy a SQLite database together with its write-ahead-log sidecars.

    The three files are one logical state; copying only the first captures the
    database as of its last checkpoint, not as it is now.
    """
    shutil.copy2(source, target)
    for suffix in SIDECARS:
        sidecar = Path(f"{source}{suffix}")
        companion = Path(f"{target}{suffix}")
        if sidecar.exists():
            shutil.copy2(sidecar, companion)
        else:
            companion.unlink(missing_ok=True)


def _unique_backup_path(directory: Path, prefix: str) -> Path:
    """A backup filename that cannot collide with an existing one.

    Timestamps are second-resolution, so two backups in the same second would
    otherwise overwrite each other — which can destroy the very file a restore
    is reading from.
    """
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    candidate = directory / f"{prefix}{stamp}.db"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{prefix}{stamp}-{counter}.db"
        counter += 1
    return candidate


def prune_backups(backup_dir: str | Path, keep: int = BACKUP_KEEP) -> None:
    """Keep only the newest ``keep`` rolling backups.

    Only files with the rolling prefix are considered, so the baseline copy and
    anything else in the folder survive.
    """
    directory = Path(backup_dir)
    if not directory.exists():
        return
    backups = sorted(directory.glob(f"{BACKUP_PREFIX}*.db"), key=lambda p: p.name)
    for stale in backups[:-keep] if keep > 0 else backups:
        stale.unlink(missing_ok=True)
        for suffix in SIDECARS:
            Path(f"{stale}{suffix}").unlink(missing_ok=True)


def ensure_baseline_backup(db_path: str | Path, backup_dir: str | Path) -> Path | None:
    """Take a one-time copy of the library as it was before rbsync touched it.

    Returns the baseline path, creating it if this is the first write.
    """
    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    existing = sorted(directory.glob(f"{ORIGINAL_PREFIX}*.db"))
    if existing:
        return existing[0]

    source = Path(db_path)
    if not source.exists():
        raise BackupFailed(f"database not found: {source}")

    target = _unique_backup_path(directory, ORIGINAL_PREFIX)
    _copy_database_set(source, target)
    if target.stat().st_size != source.stat().st_size:
        target.unlink(missing_ok=True)
        raise BackupFailed("baseline backup did not copy completely")
    log.info("baseline backup written to %s", target)
    return target


def list_backups(backup_dir: str | Path) -> list[dict]:
    """Every backup on disk, newest first, with the baseline flagged."""
    directory = Path(backup_dir)
    if not directory.exists():
        return []
    entries: list[dict] = []
    for path in directory.glob("*.db"):
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append(
            {
                "name": path.name,
                "path": str(path),
                "size": stat.st_size,
                "createdAt": datetime.fromtimestamp(stat.st_mtime).isoformat(
                    timespec="seconds"
                ),
                "isOriginal": path.name.startswith(ORIGINAL_PREFIX),
            }
        )
    return sorted(entries, key=lambda entry: entry["name"], reverse=True)


def restore_backup(
    backup_path: str | Path, db_path: str | Path, backup_dir: str | Path
) -> Path:
    """Put a backup back in place of the live database.

    Restoring is itself a destructive change, so the current database is copied
    aside first — going back must be as reversible as going forward.
    """
    source = Path(backup_path)
    target = Path(db_path)

    if not source.exists():
        raise BackupFailed(f"backup not found: {source}")
    if source.stat().st_size == 0:
        raise BackupFailed(f"backup is empty: {source}")
    if is_rekordbox_running():
        raise RekordboxRunning(
            "Rekordbox is running. Quit rekordbox completely before restoring — "
            "replacing the database underneath it will corrupt your library."
        )

    safety = backup_database(target, backup_dir) if target.exists() else None

    # Replace the whole set. Removing a sidecar the backup did not have is as
    # important as copying one it did: a leftover -wal replays its commits on
    # top of the file just restored.
    _copy_database_set(source, target)
    if target.stat().st_size != source.stat().st_size:
        if safety is not None:
            _copy_database_set(safety, target)
        raise BackupFailed("restore did not copy completely; original left in place")
    return target


def ensure_safe_to_write(db_path: str | Path, backup_dir: str | Path) -> Path:
    """Run the full pre-write gate. Returns the verified backup path."""
    if is_rekordbox_running():
        raise RekordboxRunning(
            "Rekordbox is running. Quit rekordbox completely and try again — "
            "writing while it is open can corrupt your library."
        )
    # Before anything else, preserve the pre-rbsync state exactly once.
    ensure_baseline_backup(db_path, backup_dir)
    backup = backup_database(db_path, backup_dir)
    prune_backups(backup_dir)
    return backup


def _as_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class RekordboxLibrary:
    """A handle on the rekordbox collection."""

    def __init__(self, db: Rekordbox6Database, path: Path) -> None:
        self._db = db
        self.path = path
        self._closed = False

    @classmethod
    def open(cls, path: str | Path | None = None) -> "RekordboxLibrary":
        target = Path(path) if path else default_database_path()
        if not target.exists():
            raise DatabaseNotFound(f"database not found: {target}")
        db = Rekordbox6Database(path=str(target), unlock=True)
        return cls(db, target)

    # --- reads -------------------------------------------------------------

    def load_tracks(self) -> list[LocalTrack]:
        """Read the whole collection into plain value objects.

        The matcher needs random access to every track anyway, and detaching
        from the ORM here keeps the SQLAlchemy session out of the rest of the
        codebase.
        """
        tracks: list[LocalTrack] = []
        for content in self._db.get_content().all():
            tracks.append(
                LocalTrack(
                    id=str(content.ID),
                    title=content.Title or "",
                    artist=content.ArtistName or "",
                    # DjmdContent.Length is stored in seconds.
                    length_seconds=_as_float(content.Length),
                    isrc=(content.ISRC or "").strip(),
                    folder_path=content.FolderPath or "",
                    file_name=content.FileNameL or "",
                    bit_rate=_as_int(content.BitRate),
                    file_size=_as_int(content.FileSize),
                    analysed=_as_int(content.Analysed),
                )
            )
        return tracks

    def list_playlists(self) -> list[RbPlaylist]:
        return [
            RbPlaylist(id=str(p.ID), name=p.Name or "", parent_id=str(p.ParentID or "root"))
            for p in self._db.get_playlist().all()
        ]

    def find_playlist(self, name: str, parent_id: str | None = None) -> RbPlaylist | None:
        for playlist in self._db.get_playlist().all():
            if (playlist.Name or "") != name:
                continue
            if parent_id is not None and str(playlist.ParentID or "root") != str(parent_id):
                continue
            return RbPlaylist(
                id=str(playlist.ID),
                name=playlist.Name or "",
                parent_id=str(playlist.ParentID or "root"),
            )
        return None

    def playlist_content_ids(self, playlist_id: str) -> list[str]:
        """Content ids in a playlist, in track order."""
        songs = self._db.get_playlist_songs(PlaylistID=str(playlist_id)).all()
        songs = sorted(songs, key=lambda s: _as_int(s.TrackNo))
        return [str(s.ContentID) for s in songs]

    # --- writes ------------------------------------------------------------

    def ensure_folder(self, name: str = SPOTIFY_FOLDER) -> RbPlaylist:
        """Return the named top-level playlist folder, creating it if absent."""
        existing = self.find_playlist(name, parent_id="root")
        if existing is not None:
            return existing
        created = self._db.create_playlist_folder(name)
        return RbPlaylist(
            id=str(created.ID), name=created.Name or name, parent_id=str(created.ParentID or "root")
        )

    def ensure_playlist(self, name: str, parent_id: str) -> RbPlaylist:
        """Return the named playlist under ``parent_id``, creating it if absent."""
        existing = self.find_playlist(name, parent_id=parent_id)
        if existing is not None:
            return existing
        created = self._db.create_playlist(name, parent=str(parent_id))
        return RbPlaylist(
            id=str(created.ID),
            name=created.Name or name,
            parent_id=str(created.ParentID or parent_id),
        )

    def add_tracks(self, playlist_id: str, content_ids: list[str]) -> int:
        """Append tracks that are not already in the playlist.

        Returns the number actually added. Skipping tracks already present is
        what makes re-syncing an unchanged playlist a no-op instead of steadily
        filling it with duplicates.
        """
        present = set(self.playlist_content_ids(playlist_id))
        added = 0
        for content_id in content_ids:
            if str(content_id) in present:
                continue
            self._db.add_to_playlist(str(playlist_id), str(content_id))
            present.add(str(content_id))
            added += 1
        return added

    def remove_tracks(self, playlist_id: str, content_ids: list[str]) -> int:
        """Remove the named tracks from a playlist, leaving the rest in place."""
        targets = {str(cid) for cid in content_ids}
        if not targets:
            return 0
        removed = 0
        for song in self._db.get_playlist_songs(PlaylistID=str(playlist_id)).all():
            if str(song.ContentID) in targets:
                self._db.remove_from_playlist(str(playlist_id), song)
                removed += 1
        return removed

    def commit(self) -> None:
        self._db.commit()

    def rollback(self) -> None:
        self._db.rollback()

    @contextmanager
    def transaction(self):
        """Commit everything inside the block, or roll all of it back.

        An Apply is all-or-nothing on purpose: a partially written playlist is
        harder for the user to reason about than one that was never written.
        """
        try:
            yield self
        except Exception:
            self.rollback()
            raise
        else:
            self.commit()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._db.close()
        finally:
            self._closed = True

    def __enter__(self) -> "RekordboxLibrary":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
