"""Remembering the playlist list so the app paints instantly on launch.

This is stale-while-revalidate, not a time-based cache: the stored list is only
ever a first paint, and a live fetch always follows and replaces it. So it must
never be the thing a sync is based on.
"""

import json

import pytest

from rbsync.api import build_server
from rbsync.app import AppService
from rbsync.cache import Cache
from rbsync.models import SpotifyPlaylist


class FakeSpotify:
    def __init__(self, names=("One", "Two")):
        self.names = names
        self.calls = 0

    def list_playlists(self):
        self.calls += 1
        return [
            SpotifyPlaylist(id=f"p{i}", name=name, track_count=i + 1, owner_id="me",
                            snapshot_id=f"snap{i}")
            for i, name in enumerate(self.names)
        ]

    def current_user_id(self):
        return "me"

    def close(self):
        return None


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
    svc = AppService(db_path=tmp_path / "none.db", cache=Cache(tmp_path / "cache.db"))
    fake = FakeSpotify()
    monkeypatch.setattr(AppService, "spotify", lambda self: fake)
    svc._fake = fake
    yield svc
    svc.close()


def call(server, method, params=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        payload["params"] = params
    return json.loads(server.handle_line(json.dumps(payload)))


class TestStoring:
    def test_nothing_cached_initially(self, service):
        assert service.cached_playlists() == []

    def test_listing_stores_the_result(self, service):
        service.list_playlists()
        assert [p.name for p in service.cached_playlists()] == ["One", "Two"]

    def test_cached_read_makes_no_network_call(self, service):
        service.list_playlists()
        before = service._fake.calls
        service.cached_playlists()
        assert service._fake.calls == before

    def test_all_fields_survive(self, service):
        service.list_playlists()
        restored = service.cached_playlists()[0]
        original = service.list_playlists()[0]
        assert restored == original

    def test_cache_survives_reopen(self, tmp_path, service, monkeypatch):
        service.list_playlists()
        service.close()
        reopened = AppService(db_path=tmp_path / "none.db", cache=Cache(tmp_path / "cache.db"))
        try:
            assert [p.name for p in reopened.cached_playlists()] == ["One", "Two"]
        finally:
            reopened.close()


class TestRevalidation:
    def test_a_later_fetch_replaces_the_cache(self, service):
        service.list_playlists()
        service._fake.names = ("One", "Two", "Three")
        service.list_playlists()
        assert [p.name for p in service.cached_playlists()] == ["One", "Two", "Three"]

    def test_removed_playlists_disappear(self, service):
        service.list_playlists()
        service._fake.names = ("Two",)
        service.list_playlists()
        assert [p.name for p in service.cached_playlists()] == ["Two"]


class TestApi:
    def test_cached_endpoint_returns_stored_playlists(self, service):
        server = build_server(service)
        call(server, "playlists.list")
        result = call(server, "playlists.cached")["result"]
        assert [p["name"] for p in result["playlists"]] == ["One", "Two"]

    def test_cached_endpoint_is_empty_before_any_fetch(self, service):
        server = build_server(service)
        assert call(server, "playlists.cached")["result"]["playlists"] == []

    def test_cached_endpoint_marks_selection(self, service):
        server = build_server(service)
        call(server, "playlists.list")
        call(server, "playlists.setSelected", {"playlistIds": ["p0"]})
        shown = call(server, "playlists.cached")["result"]["playlists"]
        assert next(p for p in shown if p["id"] == "p0")["selected"] is True
