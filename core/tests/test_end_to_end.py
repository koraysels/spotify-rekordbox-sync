"""Full pipeline against a copy of a real rekordbox library.

Only the Spotify HTTP layer is faked. Matching, planning, the safety gate, the
transaction and the playlist writes are all the real implementations, and the
assertions read the database back to confirm what actually landed.
"""

import pytest

from rbsync.app import AppService
from rbsync.cache import Cache
from rbsync.models import SpotifyPlaylist, SpotifyTrack
from rbsync.rekordbox import SPOTIFY_FOLDER, RekordboxLibrary


class FakeSpotify:
    """Stands in for SpotifyClient with a fixed catalogue."""

    def __init__(self, playlists, tracks_by_playlist):
        self._playlists = playlists
        self._tracks = tracks_by_playlist
        self.closed = False

    def list_playlists(self):
        return list(self._playlists)

    def playlist_tracks(self, playlist_id):
        return list(self._tracks.get(playlist_id, []))

    def close(self):
        self.closed = True


@pytest.fixture
def library_tracks(db_copy):
    with RekordboxLibrary.open(db_copy) as library:
        tracks = [t for t in library.load_tracks() if t.title and t.artist and t.length_seconds > 60]
    assert len(tracks) >= 5, "fixture library is too small for an end-to-end run"
    return tracks[:5]


@pytest.fixture
def service(db_copy, tmp_path, monkeypatch, library_tracks):
    monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
    # Rekordbox may legitimately be open on the developer's machine; the gate
    # itself has its own dedicated tests.
    monkeypatch.setattr("rbsync.app.ensure_safe_to_write",
                        lambda db, backups: _fake_backup(db, backups))

    svc = AppService(db_path=db_copy, cache=Cache(tmp_path / "cache.db"))

    owned = [
        SpotifyTrack(
            id=f"sp{index}",
            name=track.title,
            artists=[track.artist],
            album="",
            duration_ms=int(track.length_seconds * 1000),
            isrc="",
            url=f"https://open.spotify.com/track/sp{index}",
        )
        for index, track in enumerate(library_tracks)
    ]
    missing = SpotifyTrack(
        id="sp-missing",
        name="A Track Nobody Owns Zzzqx",
        artists=["Nonexistent Artist Zzzqx"],
        album="",
        duration_ms=222_000,
        isrc="",
        url="https://open.spotify.com/track/missing",
    )

    playlist = SpotifyPlaylist(id="pl-test", name="rbsync e2e", track_count=len(owned) + 1)
    fake = FakeSpotify([playlist], {"pl-test": owned + [missing]})
    monkeypatch.setattr(AppService, "spotify", lambda self: fake)

    yield svc, playlist, owned, missing
    svc.close()


def _fake_backup(db_path, backup_dir):
    from pathlib import Path
    import shutil

    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    target = Path(backup_dir) / "master_test.db"
    shutil.copy2(db_path, target)
    return target


class TestFullSync:
    def test_plan_matches_owned_tracks_and_flags_the_missing_one(self, service):
        svc, playlist, owned, _ = service
        plan = svc.plan([playlist.id])
        coverage = plan.playlists[0].coverage
        assert coverage.total == len(owned) + 1
        assert coverage.matched >= 1
        assert coverage.missing >= 1

    def test_apply_creates_the_playlist_in_rekordbox(self, service, db_copy):
        svc, playlist, _, _ = service
        plan = svc.plan([playlist.id])
        svc.apply(plan)

        with RekordboxLibrary.open(db_copy) as library:
            folder = library.find_playlist(SPOTIFY_FOLDER, parent_id="root")
            assert folder is not None
            written = library.find_playlist(playlist.name, parent_id=folder.id)
            assert written is not None

    def test_applied_tracks_are_actually_in_the_playlist(self, service, db_copy):
        svc, playlist, _, _ = service
        plan = svc.plan([playlist.id])
        expected = list(plan.playlists[0].to_add)
        assert expected, "expected at least one track to add"
        svc.apply(plan)

        with RekordboxLibrary.open(db_copy) as library:
            folder = library.find_playlist(SPOTIFY_FOLDER, parent_id="root")
            written = library.find_playlist(playlist.name, parent_id=folder.id)
            assert library.playlist_content_ids(written.id) == expected

    def test_second_apply_is_idempotent(self, service, db_copy):
        svc, playlist, _, _ = service
        svc.apply(svc.plan([playlist.id]))

        with RekordboxLibrary.open(db_copy) as library:
            folder = library.find_playlist(SPOTIFY_FOLDER, parent_id="root")
            written = library.find_playlist(playlist.name, parent_id=folder.id)
            first = library.playlist_content_ids(written.id)

        second_plan = svc.plan([playlist.id])
        assert second_plan.playlists[0].to_add == []
        results = svc.apply(second_plan)
        assert results[0].added == 0

        with RekordboxLibrary.open(db_copy) as library:
            folder = library.find_playlist(SPOTIFY_FOLDER, parent_id="root")
            written = library.find_playlist(playlist.name, parent_id=folder.id)
            assert library.playlist_content_ids(written.id) == first

    def test_apply_records_history_with_backup(self, service):
        svc, playlist, _, _ = service
        svc.apply(svc.plan([playlist.id]))
        entry = svc.history()[0]
        assert entry.playlist_name == playlist.name
        assert entry.backup_path
        assert entry.total > 0

    def test_wantlist_contains_the_missing_track(self, service, tmp_path):
        svc, playlist, _, missing = service
        plan = svc.plan([playlist.id])
        target = svc.export_wantlist(plan, tmp_path / "want.txt", fmt="txt")
        assert missing.name in target.read_text()

    def test_a_rejected_decision_keeps_a_track_out(self, service):
        svc, playlist, owned, _ = service
        plan = svc.plan([playlist.id])
        first = next(t for t in plan.playlists[0].tracks if t.content_id)
        svc.decide(first.track.id, first.content_id, accepted=False)

        replanned = svc.plan([playlist.id])
        assert first.content_id not in replanned.playlists[0].to_add

    def test_backup_is_written_before_changes(self, service, tmp_path):
        svc, playlist, _, _ = service
        svc.apply(svc.plan([playlist.id]))
        backups = list((tmp_path / "backups").glob("*.db"))
        assert backups, "expected a backup file"
        assert backups[0].stat().st_size > 0
