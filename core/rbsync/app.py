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
    default_database_path,
    ensure_safe_to_write,
    is_rekordbox_running,
)
from .spotify import SpotifyClient, Tokens, refresh
from .sync import PlaylistPlan, SyncPlan, plan_playlist, wantlist_rows, wantlist_text
from .tokens import TokenStore

log = logging.getLogger(__name__)

SETTING_CLIENT_ID = "spotify_client_id"
SETTING_AUTO_ACCEPT = "auto_accept"
SETTING_REJECT = "reject"
SETTING_ALLOW_REMOVALS = "allow_removals"


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

    def list_playlists(self) -> list[SpotifyPlaylist]:
        client = self.spotify()
        try:
            return client.list_playlists()
        finally:
            client.close()

    # --- planning ----------------------------------------------------------

    def plan(self, playlist_ids: list[str], progress=None) -> SyncPlan:
        """Build a preview of what syncing the given playlists would do."""
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
                    if progress:
                        progress(f"[{position}/{len(playlist_ids)}] {playlist.name}")
                    tracks = client.playlist_tracks(playlist_id)
                    existing: list[str] = []
                    if folder is not None:
                        target = library.find_playlist(playlist.name, parent_id=folder.id)
                        if target is not None:
                            existing = library.playlist_content_ids(target.id)
                    plans.append(
                        plan_playlist(
                            playlist, tracks, self.index, self.cache, existing,
                            config=self.match_config(),
                            allow_removals=self.allow_removals(),
                        )
                    )
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
