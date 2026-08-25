import json

import pytest

from rbsync.api import build_server
from rbsync.app import AppService
from rbsync.cache import Cache


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
    svc = AppService(db_path=tmp_path / "nonexistent.db", cache=Cache(tmp_path / "cache.db"))
    yield svc
    svc.close()


@pytest.fixture
def server(service):
    return build_server(service)


def call(server, method, params=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        payload["params"] = params
    return json.loads(server.handle_line(json.dumps(payload)))


class TestSettings:
    def test_defaults_are_returned(self, server):
        result = call(server, "settings.get")["result"]
        assert result["autoAccept"] == 0.88
        assert result["reject"] == 0.62
        assert result["allowRemovals"] is False

    def test_settings_round_trip(self, server):
        call(server, "settings.set", {"autoAccept": 0.95, "allowRemovals": True})
        result = call(server, "settings.get")["result"]
        assert result["autoAccept"] == 0.95
        assert result["allowRemovals"] is True

    def test_client_id_is_persisted(self, server):
        call(server, "settings.set", {"clientId": "abc123"})
        assert call(server, "settings.get")["result"]["clientId"] == "abc123"


class TestSelection:
    def test_selection_defaults_to_empty(self, server):
        assert call(server, "status")["result"]["selected_playlists"] == []

    def test_selection_round_trips(self, server):
        call(server, "playlists.setSelected", {"playlistIds": ["a", "b"]})
        assert sorted(call(server, "status")["result"]["selected_playlists"]) == ["a", "b"]

    def test_selection_can_be_cleared(self, server):
        call(server, "playlists.setSelected", {"playlistIds": ["a"]})
        call(server, "playlists.setSelected", {"playlistIds": []})
        assert call(server, "status")["result"]["selected_playlists"] == []


class TestGuards:
    def test_plan_without_selection_is_an_error(self, server):
        response = call(server, "sync.plan")
        assert response["error"]["code"] == -32000
        assert "No playlists selected" in response["error"]["message"]

    def test_apply_without_plan_is_an_error(self, server):
        response = call(server, "sync.apply")
        assert "Nothing to apply" in response["error"]["message"]

    def test_export_without_plan_is_an_error(self, server):
        response = call(server, "wantlist.export")
        assert "Nothing to export" in response["error"]["message"]

    def test_wantlist_without_plan_is_empty_not_error(self, server):
        assert call(server, "wantlist.get")["result"]["rows"] == []

    def test_auth_complete_without_begin_is_an_error(self, server):
        response = call(server, "auth.complete", {"code": "x"})
        assert "no sign-in in progress" in response["error"]["message"]


class TestReview:
    def test_bulk_decisions_are_recorded(self, server, service):
        call(server, "review.decide", {"decisions": [
            {"spotify_id": "s1", "content_id": "rb1", "accepted": True},
            {"spotify_id": "s2", "content_id": "rb2", "accepted": False},
        ]})
        assert service.cache.get_decision("s1").accepted is True
        assert service.cache.get_decision("s2").accepted is False
