"""Viewing a playlist's contents without planning a sync."""

import json

import pytest

from rbsync.api import build_server
from rbsync.app import AppService
from rbsync.cache import Cache
from rbsync.models import SpotifyPlaylist, SpotifyTrack
from rbsync.spotify import PlaylistAccessDenied


class FakeSpotify:
    def list_playlists(self):
        return [SpotifyPlaylist(id="ok", name="Mine", track_count=2, owner_id="me")]

    def current_user_id(self):
        return "me"

    def playlist_tracks(self, playlist_id):
        if playlist_id == "denied":
            raise PlaylistAccessDenied(
                "Spotify will not share the contents of playlist denied. "
                "It only serves playlists you own or collaborate on."
            )
        return [
            SpotifyTrack(id="s1", name="Versace", artists=["Migos"], album="YRN",
                         duration_ms=195_000, isrc="X1", url="u1"),
            SpotifyTrack(id="s2", name="Panda", artists=["Desiigner"], album="",
                         duration_ms=245_000, isrc="", url="u2"),
        ]

    def close(self):
        return None


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
    service = AppService(db_path=tmp_path / "none.db", cache=Cache(tmp_path / "cache.db"))
    monkeypatch.setattr(AppService, "spotify", lambda self: FakeSpotify())
    yield build_server(service)
    service.close()


def call(server, method, params=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        payload["params"] = params
    return json.loads(server.handle_line(json.dumps(payload)))


class TestBrowse:
    def test_returns_the_playlist_tracks(self, server):
        result = call(server, "playlists.tracks", {"playlistId": "ok"})["result"]
        assert [t["name"] for t in result["tracks"]] == ["Versace", "Panda"]

    def test_tracks_use_the_ui_wire_format(self, server):
        track = call(server, "playlists.tracks", {"playlistId": "ok"})["result"]["tracks"][0]
        assert track["durationMs"] == 195_000
        assert track["display"] == "Migos - Versace"
        assert track["isrc"] == "X1"

    def test_no_error_on_a_readable_playlist(self, server):
        assert call(server, "playlists.tracks", {"playlistId": "ok"})["result"]["error"] is None

    def test_forbidden_playlist_reports_an_error_instead_of_failing(self, server):
        result = call(server, "playlists.tracks", {"playlistId": "denied"})["result"]
        assert result["tracks"] == []
        assert "own or collaborate" in result["error"]

    def test_missing_playlist_id_is_an_error(self, server):
        response = call(server, "playlists.tracks")
        assert response["error"]["code"] == -32000
