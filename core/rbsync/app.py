"""The service layer shared by the CLI and the JSON-RPC sidecar.

Everything above this line is a transport. Everything below it is a component
with a single job. This module is where they are wired together, and it is the
only place that knows the whole flow.
"""

from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .branding import default_client_id
from .cache import Cache
from .matcher import Band, MatchConfig, TrackIndex
from .models import Coverage, SpotifyPlaylist, SpotifyTrack
from .rekordbox import (
    SPOTIFY_FOLDER,
    RekordboxLibrary,
    backup_database,
    default_database_path,
    ensure_baseline_backup,
    ensure_safe_to_write,
    is_rekordbox_running,
    list_backups as _list_backups,
    restore_backup as _restore_backup,
)
from .spotify import PlaylistAccessDenied, SpotifyClient, Tokens, refresh
from .persist import plan_from_json, plan_to_json
from .sync import PlaylistPlan, SyncPlan, plan_playlist, wantlist_rows, wantlist_text
from .tokens import TokenStore

log = logging.getLogger(__name__)

SETTING_CLIENT_ID = "spotify_client_id"
SETTING_AUTO_ACCEPT = "auto_accept"
SETTING_REJECT = "reject"
SETTING_ALLOW_REMOVALS = "allow_removals"
SETTING_ONLY_SYNCABLE = "only_syncable"

# Where macOS mounts external drives. Paths beneath a directory here belong to a
# volume that may simply not be plugged in.
VOLUME_PREFIX = "/Volumes"


@dataclass(slots=True)
class ApplyResult:
    playlist_id: str
    playlist_name: str
    added: int
    removed: int
    backup_path: str


class AppService:
    def __init__(self, db_path: Path | None = None, cache: Cache | None = None) -> None:
        self._db_path = Path(db_path) if db_path else None
        self.cache = cache or Cache(paths.cache_path())
        self.tokens = TokenStore(paths.tokens_path())
        self._index: TrackIndex | None = None
        self._track_count = 0

    # --- configuration -----------------------------------------------------

    @property
    def db_path(self) -> Path:
        """Which rekordbox database to use.

        ``RBSYNC_DB_PATH`` exists so the app can be pointed at a copy — for
        testing a sync without any risk to the real library.
        """
        if self._db_path is None:
            override = os.environ.get("RBSYNC_DB_PATH")
            self._db_path = Path(override) if override else default_database_path()
        return self._db_path

    def match_config(self) -> MatchConfig:
        """Thresholds come from settings; the defaults are only defaults."""
        return MatchConfig(
            auto_accept=float(self.cache.get_setting(SETTING_AUTO_ACCEPT, "0.88")),
            reject=float(self.cache.get_setting(SETTING_REJECT, "0.62")),
        )

    def allow_removals(self) -> bool:
        return self.cache.get_setting(SETTING_ALLOW_REMOVALS, "0") == "1"

    def only_syncable(self) -> bool:
        """Hide playlists Spotify will not serve. On by default.

        Since February 2026 Spotify returns contents only for playlists the user
        owns or collaborates on; the rest answer 403 and cannot be synced at
        all, so listing them is just noise.
        """
        return self.cache.get_setting(SETTING_ONLY_SYNCABLE, "1") == "1"

    def client_id(self) -> str:
        """A Client ID the user set, otherwise the one bundled with the build."""
        return (self.cache.get_setting(SETTING_CLIENT_ID, "") or "").strip() or default_client_id()

    def status(self) -> dict:
        return {
            "db_path": str(self.db_path) if self._safe_db_path() else None,
            "rekordbox_running": is_rekordbox_running(),
            "tracks_indexed": self._track_count,
            "authenticated": self.tokens.load() is not None,
            "client_id_set": bool(self.client_id()),
            "client_id_is_bundled": not (self.cache.get_setting(SETTING_CLIENT_ID, "") or "").strip(),
            "selected_playlists": self.cache.get_selected_playlists(),
        }

    def _safe_db_path(self) -> bool:
        try:
            self.db_path
            return True
        except Exception:
            return False

    # --- library -----------------------------------------------------------

    def load_library(self, progress=None) -> int:
        """Read the rekordbox collection and build the match index."""
        if progress:
            progress("Opening rekordbox database")
        with RekordboxLibrary.open(self.db_path) as library:
            tracks = library.load_tracks()
        if progress:
            progress(f"Indexing {len(tracks)} tracks")
        self._index = TrackIndex(tracks, self.match_config())
        self._track_count = len(tracks)
        return self._track_count

    @property
    def index(self) -> TrackIndex:
        if self._index is None:
            self.load_library()
        assert self._index is not None
        return self._index

    # --- spotify -----------------------------------------------------------

    def spotify(self) -> SpotifyClient:
        tokens = self.tokens.load()
        if tokens is None:
            raise RuntimeError("Not connected to Spotify. Run the sign-in flow first.")
        if tokens.expired and tokens.refresh_token:
            tokens = refresh(self.client_id(), tokens)
            self.tokens.save(tokens)
        return SpotifyClient(tokens)

    @staticmethod
    def _playlist_to_json(playlist: SpotifyPlaylist) -> dict:
        return {
            "id": playlist.id,
            "name": playlist.name,
            "track_count": playlist.track_count,
            "owner": playlist.owner,
            "snapshot_id": playlist.snapshot_id,
            "owner_id": playlist.owner_id,
            "collaborative": playlist.collaborative,
        }

    @staticmethod
    def _playlist_from_json(data: dict) -> SpotifyPlaylist:
        return SpotifyPlaylist(
            id=data.get("id", ""),
            name=data.get("name", ""),
            track_count=int(data.get("track_count") or 0),
            owner=data.get("owner", ""),
            snapshot_id=data.get("snapshot_id", ""),
            owner_id=data.get("owner_id", ""),
            collaborative=bool(data.get("collaborative")),
        )

    def cached_playlists(self) -> list[SpotifyPlaylist]:
        """The last known playlist list, for painting the UI before the fetch."""
        return [self._playlist_from_json(item) for item in self.cache.get_playlists()]

    def list_playlists(self) -> list[SpotifyPlaylist]:
        client = self.spotify()
        try:
            playlists = client.list_playlists()
            if not self.only_syncable():
                self.cache.save_playlists([self._playlist_to_json(p) for p in playlists])
                return playlists
            me = client.current_user_id()
            # Collaborative playlists are readable even when owned by someone
            # else, so filtering on ownership alone would hide working ones.
            visible = [
                p for p in playlists
                if p.collaborative or not p.owner_id or not me or p.owner_id == me
            ]
            self.cache.save_playlists([self._playlist_to_json(p) for p in visible])
            return visible
        finally:
            client.close()

    # --- plan caching ------------------------------------------------------

    def plan_fingerprint(self) -> str:
        """Identifies everything a plan's outcome depends on, except the playlist.

        If any of these change, a stored plan could write something different
        from what it says, so it must be recomputed rather than reused.
        """
        config = self.match_config()
        return ":".join(
            [
                str(self._track_count),
                f"{config.auto_accept:.4f}",
                f"{config.reject:.4f}",
                "1" if self.allow_removals() else "0",
                self.cache.decisions_marker(),
            ]
        )

    def cached_plans(self, playlist_ids: list[str]) -> list[PlaylistPlan]:
        """Stored plans for these playlists, without touching the network."""
        plans: list[PlaylistPlan] = []
        for playlist_id in playlist_ids:
            stored = self.cache.get_plan(playlist_id)
            if stored is None:
                continue
            try:
                plans.append(plan_from_json(stored.payload))
            except Exception:  # noqa: BLE001 - a bad payload is just a cache miss
                log.warning("discarding unreadable stored plan for %s", playlist_id)
                self.cache.delete_plan(playlist_id)
        return plans

    def stored_plan_state(self, playlist_ids: list[str]) -> dict[str, dict]:
        """Per-playlist metadata about what is stored, for the UI to show."""
        state: dict[str, dict] = {}
        fingerprint = self.plan_fingerprint()
        for playlist_id in playlist_ids:
            stored = self.cache.get_plan(playlist_id)
            if stored is None:
                continue
            state[playlist_id] = {
                "snapshotId": stored.snapshot_id,
                "createdAt": stored.created_at,
                "fingerprintMatches": stored.fingerprint == fingerprint,
            }
        return state

    # --- planning ----------------------------------------------------------

    def plan(self, playlist_ids: list[str], progress=None, force: bool = False) -> SyncPlan:
        """Build a preview of what syncing the given playlists would do.

        A plan stored from an earlier run is reused when nothing that affects
        its outcome has changed: the playlist's Spotify snapshot, the match
        settings, the recorded decisions and the size of the collection.
        """
        fingerprint = self.plan_fingerprint()
        client = self.spotify()
        try:
            all_playlists = {p.id: p for p in client.list_playlists()}
            plans: list[PlaylistPlan] = []
            with RekordboxLibrary.open(self.db_path) as library:
                folder = library.find_playlist(SPOTIFY_FOLDER, parent_id="root")
                for position, playlist_id in enumerate(playlist_ids, start=1):
                    playlist = all_playlists.get(playlist_id)
                    if playlist is None:
                        continue

                    if not force:
                        stored = self.cache.get_plan(playlist_id)
                        if (
                            stored is not None
                            and stored.fingerprint == fingerprint
                            and stored.snapshot_id == (playlist.snapshot_id or "")
                        ):
                            if progress:
                                progress(f"[{position}/{len(playlist_ids)}] {playlist.name} (stored)")
                            try:
                                plans.append(plan_from_json(stored.payload))
                                continue
                            except Exception:  # noqa: BLE001
                                log.warning("stored plan unusable for %s", playlist_id)
                                self.cache.delete_plan(playlist_id)

                    if progress:
                        progress(f"[{position}/{len(playlist_ids)}] {playlist.name}")
                    try:
                        tracks = client.playlist_tracks(playlist_id)
                    except PlaylistAccessDenied as exc:
                        # One unreadable playlist must not abort the others.
                        log.warning("skipping %s: %s", playlist.name, exc)
                        plans.append(PlaylistPlan(playlist=playlist, error=str(exc)))
                        continue
                    existing: list[str] = []
                    if folder is not None:
                        target = library.find_playlist(playlist.name, parent_id=folder.id)
                        if target is not None:
                            existing = library.playlist_content_ids(target.id)
                    computed = plan_playlist(
                        playlist, tracks, self.index, self.cache, existing,
                        config=self.match_config(),
                        allow_removals=self.allow_removals(),
                    )
                    self.cache.save_plan(
                        playlist_id,
                        snapshot_id=playlist.snapshot_id or "",
                        fingerprint=fingerprint,
                        payload=plan_to_json(computed),
                    )
                    plans.append(computed)
            return SyncPlan(playlists=plans)
        finally:
            client.close()

    # --- applying ----------------------------------------------------------

    def apply(self, plan: SyncPlan, progress=None) -> list[ApplyResult]:
        """Write an approved plan to rekordbox.

        The safety gate runs first and raises rather than proceeding: refusing
        to write is always recoverable, writing into a running rekordbox is not.
        """
        if progress:
            progress("Checking that rekordbox is closed")
        backup = ensure_safe_to_write(self.db_path, paths.backups_dir())
        if progress:
            progress(f"Backed up to {backup.name}")

        results: list[ApplyResult] = []
        with RekordboxLibrary.open(self.db_path) as library:
            with library.transaction():
                folder = library.ensure_folder(SPOTIFY_FOLDER)
                for playlist_plan in plan.playlists:
                    name = playlist_plan.playlist.name
                    if progress:
                        progress(f"Writing {name}")
                    target = library.ensure_playlist(name, folder.id)
                    added = library.add_tracks(target.id, playlist_plan.to_add)
                    removed = library.remove_tracks(target.id, playlist_plan.to_remove)
                    results.append(
                        ApplyResult(
                            playlist_id=playlist_plan.playlist.id,
                            playlist_name=name,
                            added=added,
                            removed=removed,
                            backup_path=str(backup),
                        )
                    )

        # Applying changes the rekordbox library, so every stored plan is now
        # describing a state that no longer exists.
        self.cache.clear_plans()

        for playlist_plan, result in zip(plan.playlists, results):
            self.cache.record_sync(
                playlist_plan.playlist.id,
                added=result.added,
                removed=result.removed,
                matched=playlist_plan.coverage.matched,
                total=playlist_plan.coverage.total,
                playlist_name=result.playlist_name,
                backup_path=result.backup_path,
            )
        return results

    def history(self, playlist_id: str | None = None, limit: int = 50) -> list:
        """Past syncs, newest first."""
        return self.cache.get_history(playlist_id=playlist_id, limit=limit)

    # --- backups -----------------------------------------------------------

    def list_backups(self) -> list[dict]:
        return _list_backups(paths.backups_dir())

    def create_backup(self) -> dict:
        """Take a backup right now, without writing anything.

        Lets someone capture a known-good state before experimenting, rather
        than relying on the copy a sync happens to make.
        """
        directory = paths.backups_dir()
        ensure_baseline_backup(self.db_path, directory)
        path = backup_database(self.db_path, directory)
        stat = path.stat()
        return {
            "name": path.name,
            "path": str(path),
            "size": stat.st_size,
            "isOriginal": False,
        }

    def restore_backup(self, backup_path: str) -> dict:
        """Put a backup back. Only files inside our own backup folder qualify.

        Restore overwrites the live rekordbox database, so accepting an
        arbitrary path would turn this into a way to clobber the library with
        any file on disk.
        """
        directory = paths.backups_dir().resolve()
        candidate = Path(backup_path).resolve()
        if candidate.parent != directory:
            raise ValueError("Only backups created by this app can be restored.")

        restored = _restore_backup(candidate, self.db_path, directory)
        # The library on disk is different now; anything derived from it is stale.
        self.cache.clear_plans()
        self._index = None
        self._track_count = 0
        return {"restored": str(restored), "from": str(candidate)}

    # --- file checks -------------------------------------------------------

    def verify_files(self, content_ids: list[str]) -> dict[str, dict]:
        """Check that matched rekordbox rows point at files that still exist.

        rekordbox keeps the path it imported; if the file was moved or deleted
        outside the app, the row survives and the track will not play. A synced
        playlist made of those is exactly the failure this tool exists to avoid.
        """
        results: dict[str, dict] = {}
        for content_id in content_ids:
            track = self.index.get(content_id)
            path = (track.folder_path if track else "") or ""
            if not path:
                results[content_id] = {
                    "exists": False, "status": "unknown", "path": "", "size": 0, "volume": "",
                }
                continue

            candidate = Path(path)
            volume = self._volume_of(path)
            if volume and not Path(volume).exists():
                # The drive is not plugged in. Nothing is lost, so this must not
                # be reported the same way as a deleted file.
                results[content_id] = {
                    "exists": False, "status": "offline", "path": str(candidate),
                    "size": 0, "volume": volume,
                }
                continue

            try:
                stat = candidate.stat()
                results[content_id] = {
                    "exists": True, "status": "ok", "path": str(candidate),
                    "size": stat.st_size, "volume": volume,
                }
            except OSError:
                results[content_id] = {
                    "exists": False, "status": "missing", "path": str(candidate),
                    "size": 0, "volume": volume,
                }
        return results

    @staticmethod
    def _volume_of(path: str) -> str:
        """The mount point a path belongs to, or empty for the internal disk."""
        prefix = VOLUME_PREFIX.rstrip("/") + "/"
        if not path.startswith(prefix):
            return ""
        remainder = path[len(prefix):]
        name = remainder.split("/", 1)[0]
        return f"{prefix}{name}" if name else ""

    def library_health(self) -> dict:
        """How much of the collection would actually play right now.

        Separates "the drive is not plugged in" from "the file is gone", because
        the first is fixed by reconnecting a drive and the second is not. The
        per-volume breakdown names which drive to reconnect.
        """
        counts = {"ok": 0, "missing": 0, "offline": 0, "unknown": 0}
        offline_volumes: dict[str, int] = {}
        missing_volume_cache: dict[str, bool] = {}

        for track in self.index.tracks:
            path = track.folder_path or ""
            if not path:
                counts["unknown"] += 1
                continue

            volume = self._volume_of(path)
            if volume:
                mounted = missing_volume_cache.get(volume)
                if mounted is None:
                    mounted = Path(volume).exists()
                    missing_volume_cache[volume] = mounted
                if not mounted:
                    counts["offline"] += 1
                    offline_volumes[volume] = offline_volumes.get(volume, 0) + 1
                    continue

            counts["ok" if Path(path).exists() else "missing"] += 1

        return {
            **counts,
            "total": len(self.index.tracks),
            "volumes": [
                {"volume": volume, "count": count}
                for volume, count in sorted(
                    offline_volumes.items(), key=lambda item: -item[1]
                )
            ],
        }

    def rekordbox_playlists(self) -> list[dict]:
        """What is actually inside the rekordbox Spotify folder right now.

        Read straight from master.db rather than from our own records, so it
        shows what rekordbox will really open.
        """
        with RekordboxLibrary.open(self.db_path) as library:
            folder = library.find_playlist(SPOTIFY_FOLDER, parent_id="root")
            if folder is None:
                return []
            playlists = [
                p for p in library.list_playlists() if str(p.parent_id) == str(folder.id)
            ]
            return [
                {
                    "id": p.id,
                    "name": p.name,
                    "trackCount": len(library.playlist_content_ids(p.id)),
                }
                for p in sorted(playlists, key=lambda p: p.name.lower())
            ]

    # --- review ------------------------------------------------------------

    def decide(self, spotify_id: str, content_id: str, accepted: bool) -> None:
        self.cache.remember_decision(spotify_id, content_id, accepted)

    def decide_bulk(self, decisions: list[dict]) -> int:
        """Apply many review decisions at once.

        Bulk is the normal path, not a shortcut: reviewing hundreds of tracks
        one dialog at a time is not a workflow anybody finishes.
        """
        for decision in decisions:
            self.decide(
                decision["spotify_id"], decision.get("content_id", ""),
                bool(decision.get("accepted")),
            )
        return len(decisions)

    # --- export ------------------------------------------------------------

    def export_wantlist(
        self, plan: SyncPlan, path: Path | None = None, fmt: str | None = None
    ) -> Path:
        """Write the missing-tracks list.

        Two formats, because they serve different jobs: CSV for keeping track of
        what to buy, and plain ``Artist - Title`` lines for pasting straight
        into a search tool.
        """
        target = Path(path) if path else paths.exports_dir() / "wantlist.csv"
        if fmt is None:
            fmt = "txt" if target.suffix.lower() in (".txt", ".text") else "csv"
        if fmt not in ("csv", "txt"):
            raise ValueError(f"unsupported wantlist format: {fmt}")

        target.parent.mkdir(parents=True, exist_ok=True)

        if fmt == "txt":
            target.write_text(wantlist_text(plan.playlists) + "\n", encoding="utf-8")
            return target

        rows = wantlist_rows(plan.playlists, deduplicate=True)
        fields = ["playlist", "artist", "title", "album", "duration_seconds", "isrc", "url"]
        with open(target, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return target

    def close(self) -> None:
        self.cache.close()
