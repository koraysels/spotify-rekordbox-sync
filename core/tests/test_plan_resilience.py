"""A playlist the user cannot read must not sink the rest of the sync."""

import pytest

from rbsync.app import AppService
from rbsync.cache import Cache
from rbsync.matcher import TrackIndex
from rbsync.models import LocalTrack, SpotifyPlaylist, SpotifyTrack
from rbsync.spotify import PlaylistAccessDenied


class PartlyForbiddenSpotify:
    def __init__(self):
        self.playlists = [
            SpotifyPlaylist(id="ok", name="Mine", track_count=1, owner_id="me"),
            SpotifyPlaylist(id="denied", name="Followed", track_count=9, owner_id="someone"),
        ]

    def list_playlists(self):
        return list(self.playlists)

    def playlist_tracks(self, playlist_id):
        if playlist_id == "denied":
            raise PlaylistAccessDenied(
                "Spotify will not share the contents of playlist denied. "
                "It only serves playlists you own or collaborate on."
            )
        return [
            SpotifyTrack(id="s1", name="Versace", artists=["Migos"], album="",
                         duration_ms=195_000, isrc="", url="")
        ]

    def close(self):
        return None


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
    svc = AppService(db_path=tmp_path / "none.db", cache=Cache(tmp_path / "cache.db"))
    svc._index = TrackIndex([
        LocalTrack(id="rb1", title="Versace", artist="Migos", length_seconds=195)
    ])
    svc._track_count = 1
    monkeypatch.setattr(AppService, "spotify", lambda self: PartlyForbiddenSpotify())
    # The planner reads existing playlist contents from rekordbox; there is no
    # database in this test, so treat the library as absent.
    monkeypatch.setattr("rbsync.app.RekordboxLibrary.open", lambda path: _NoLibrary())
    yield svc
    svc.close()


class _NoLibrary:
    def find_playlist(self, *a, **k):
        return None

    def playlist_content_ids(self, *a, **k):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


class TestForbiddenPlaylist:
    def test_readable_playlist_is_still_planned(self, service):
        plan = service.plan(["ok", "denied"])
        names = {p.playlist.name for p in plan.playlists}
        assert "Mine" in names

    def test_forbidden_playlist_is_reported_not_raised(self, service):
        plan = service.plan(["ok", "denied"])
        denied = next(p for p in plan.playlists if p.playlist.id == "denied")
        assert denied.error
        assert "own or collaborate" in denied.error

    def test_forbidden_playlist_has_nothing_to_write(self, service):
        plan = service.plan(["ok", "denied"])
        denied = next(p for p in plan.playlists if p.playlist.id == "denied")
        assert denied.to_add == []
        assert denied.tracks == []

    def test_forbidden_playlist_does_not_distort_coverage(self, service):
        plan = service.plan(["ok", "denied"])
        assert plan.coverage.total == 1

    def test_readable_playlist_matches_normally(self, service):
        plan = service.plan(["ok", "denied"])
        ok = next(p for p in plan.playlists if p.playlist.id == "ok")
        assert ok.to_add == ["rb1"]
        assert ok.error is None
