"""Reusing a stored plan — and knowing when not to.

A stale plan is dangerous: it gets applied to the user's rekordbox library. Any
change that could alter the outcome must invalidate it.
"""

import pytest

from rbsync.app import AppService
from rbsync.cache import Cache
from rbsync.matcher import TrackIndex
from rbsync.models import LocalTrack, SpotifyPlaylist, SpotifyTrack


class CountingSpotify:
    """Counts fetches so tests can prove the cache avoided the network."""

    fetches = 0

    def __init__(self, snapshot="snap1"):
        self.snapshot = snapshot

    def list_playlists(self):
        return [SpotifyPlaylist(id="pl1", name="Bangers", track_count=1,
                                owner_id="me", snapshot_id=self.snapshot)]

    def current_user_id(self):
        return "me"

    def playlist_tracks(self, playlist_id):
        CountingSpotify.fetches += 1
        return [SpotifyTrack(id="s1", name="Versace", artists=["Migos"], album="",
                             duration_ms=195_000, isrc="", url="")]

    def close(self):
        return None


class _NoLibrary:
    def find_playlist(self, *a, **k):
        return None

    def playlist_content_ids(self, *a, **k):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
    CountingSpotify.fetches = 0
    svc = AppService(db_path=tmp_path / "none.db", cache=Cache(tmp_path / "cache.db"))
    svc._index = TrackIndex([
        LocalTrack(id="rb1", title="Versace", artist="Migos", length_seconds=195)
    ])
    svc._track_count = 1
    monkeypatch.setattr(AppService, "spotify", lambda self: CountingSpotify())
    monkeypatch.setattr("rbsync.app.RekordboxLibrary.open", lambda path: _NoLibrary())
    yield svc
    svc.close()


class TestReuse:
    def test_second_plan_does_not_refetch(self, service):
        service.plan(["pl1"])
        assert CountingSpotify.fetches == 1
        service.plan(["pl1"])
        assert CountingSpotify.fetches == 1

    def test_reused_plan_has_the_same_content(self, service):
        first = service.plan(["pl1"])
        second = service.plan(["pl1"])
        assert second.playlists[0].to_add == first.playlists[0].to_add
        assert second.playlists[0].coverage.as_dict() == first.playlists[0].coverage.as_dict()

    def test_force_bypasses_the_cache(self, service):
        service.plan(["pl1"])
        service.plan(["pl1"], force=True)
        assert CountingSpotify.fetches == 2


class TestInvalidation:
    def test_a_changed_playlist_is_replanned(self, service, monkeypatch):
        service.plan(["pl1"])
        # Spotify bumps snapshot_id whenever a playlist is edited.
        monkeypatch.setattr(AppService, "spotify", lambda self: CountingSpotify("snap2"))
        service.plan(["pl1"])
        assert CountingSpotify.fetches == 2

    def test_changing_thresholds_invalidates(self, service):
        service.plan(["pl1"])
        service.cache.set_setting("auto_accept", "0.95")
        service.plan(["pl1"])
        assert CountingSpotify.fetches == 2

    def test_a_new_decision_invalidates(self, service):
        service.plan(["pl1"])
        service.decide("s1", "rb1", accepted=False)
        service.plan(["pl1"])
        assert CountingSpotify.fetches == 2

    def test_changing_removal_policy_invalidates(self, service):
        service.plan(["pl1"])
        service.cache.set_setting("allow_removals", "1")
        service.plan(["pl1"])
        assert CountingSpotify.fetches == 2

    def test_a_changed_collection_invalidates(self, service):
        service.plan(["pl1"])
        service._track_count = 12
        service.plan(["pl1"])
        assert CountingSpotify.fetches == 2

    def test_applying_clears_the_stored_plan(self, service, monkeypatch):
        plan = service.plan(["pl1"])
        monkeypatch.setattr("rbsync.app.ensure_safe_to_write",
                            lambda db, backups: __import__("pathlib").Path(db))

        class _Writable(_NoLibrary):
            def ensure_folder(self, *a, **k):
                return SpotifyPlaylist(id="f", name="Spotify", track_count=0)

            def ensure_playlist(self, *a, **k):
                return SpotifyPlaylist(id="p", name="Bangers", track_count=0)

            def add_tracks(self, *a, **k):
                return 1

            def remove_tracks(self, *a, **k):
                return 0

            def transaction(self):
                return self

        monkeypatch.setattr("rbsync.app.RekordboxLibrary.open", lambda path: _Writable())
        service.apply(plan)
        # The library changed underneath, so the stored plan must not be reused.
        assert service.cache.get_plan("pl1") is None


class TestStoredPlans:
    def test_cached_plans_load_without_the_network(self, service):
        service.plan(["pl1"])
        CountingSpotify.fetches = 0
        restored = service.cached_plans(["pl1"])
        assert CountingSpotify.fetches == 0
        assert restored[0].to_add == ["rb1"]

    def test_unknown_playlist_yields_nothing(self, service):
        assert service.cached_plans(["nope"]) == []
