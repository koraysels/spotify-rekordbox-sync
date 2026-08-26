"""Hiding playlists Spotify refuses to serve.

Owned playlists always work. Collaborative playlists work even when owned by
someone else. Everything else answers 403, so it is noise in the list.
"""

import pytest

from rbsync.api import build_server
from rbsync.app import AppService
from rbsync.cache import Cache
from rbsync.models import SpotifyPlaylist

import json


class FakeSpotify:
    def __init__(self):
        self.playlists = [
            SpotifyPlaylist(id="mine", name="Mine", track_count=1, owner_id="me"),
            SpotifyPlaylist(id="collab", name="Collab", track_count=1,
                            owner_id="other", collaborative=True),
            SpotifyPlaylist(id="followed", name="Followed", track_count=1, owner_id="other"),
        ]

    def list_playlists(self):
        return list(self.playlists)

    def current_user_id(self):
        return "me"

    def close(self):
        return None


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
    svc = AppService(db_path=tmp_path / "none.db", cache=Cache(tmp_path / "cache.db"))
    monkeypatch.setattr(AppService, "spotify", lambda self: FakeSpotify())
    yield svc
    svc.close()


def call(server, method, params=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        payload["params"] = params
    return json.loads(server.handle_line(json.dumps(payload)))


class TestDefault:
    def test_filter_is_on_by_default(self, service):
        assert service.only_syncable() is True

    def test_hides_followed_playlists_by_default(self, service):
        names = {p.name for p in service.list_playlists()}
        assert names == {"Mine", "Collab"}

    def test_keeps_collaborative_playlists(self, service):
        assert any(p.id == "collab" for p in service.list_playlists())


class TestDisabled:
    def test_shows_everything_when_turned_off(self, service):
        service.cache.set_setting("only_syncable", "0")
        assert len(service.list_playlists()) == 3

    def test_setting_round_trips(self, service):
        service.cache.set_setting("only_syncable", "0")
        assert service.only_syncable() is False
        service.cache.set_setting("only_syncable", "1")
        assert service.only_syncable() is True


class TestApi:
    def test_settings_expose_the_flag(self, service):
        server = build_server(service)
        assert call(server, "settings.get")["result"]["onlySyncable"] is True

    def test_settings_can_change_the_flag(self, service):
        server = build_server(service)
        call(server, "settings.set", {"onlySyncable": False})
        assert call(server, "settings.get")["result"]["onlySyncable"] is False

    def test_playlist_list_respects_the_flag(self, service):
        server = build_server(service)
        shown = call(server, "playlists.list")["result"]["playlists"]
        assert {p["name"] for p in shown} == {"Mine", "Collab"}

        call(server, "settings.set", {"onlySyncable": False})
        shown = call(server, "playlists.list")["result"]["playlists"]
        assert len(shown) == 3
