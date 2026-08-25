import json
import urllib.error
import urllib.request

import pytest

from rbsync.app import AppService
from rbsync.cache import Cache
from rbsync.httpbridge import serve_in_background


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
    service = AppService(db_path=tmp_path / "none.db", cache=Cache(tmp_path / "cache.db"))
    server, thread = serve_in_background(service, port=0)
    yield server, service
    server.shutdown()
    thread.join(timeout=5)
    service.close()


def post(server, payload):
    port = server.server_address[1]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/rpc",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


class TestBridge:
    def test_ping_round_trips(self, bridge):
        server, _ = bridge
        assert post(server, {"jsonrpc": "2.0", "id": 1, "method": "ping"})["result"]["pong"] is True

    def test_status_is_served(self, bridge):
        server, _ = bridge
        result = post(server, {"jsonrpc": "2.0", "id": 2, "method": "status"})
        assert "rekordbox_running" in result["result"]

    def test_unknown_method_returns_rpc_error(self, bridge):
        server, _ = bridge
        result = post(server, {"jsonrpc": "2.0", "id": 3, "method": "nope"})
        assert result["error"]["code"] == -32601

    def test_settings_persist_across_calls(self, bridge):
        server, _ = bridge
        post(server, {"jsonrpc": "2.0", "id": 4, "method": "settings.set",
                      "params": {"autoAccept": 0.91}})
        result = post(server, {"jsonrpc": "2.0", "id": 5, "method": "settings.get"})
        assert result["result"]["autoAccept"] == 0.91

    def test_cors_headers_allow_the_dev_server(self, bridge):
        server, _ = bridge
        port = server.server_address[1]
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/rpc",
            data=json.dumps({"jsonrpc": "2.0", "id": 6, "method": "ping"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.headers["Access-Control-Allow-Origin"] == "*"

    def test_unknown_path_is_not_found(self, bridge):
        server, _ = bridge
        port = server.server_address[1]
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/elsewhere", timeout=5)
        assert excinfo.value.code == 404

    def test_binds_loopback_only(self, bridge):
        server, _ = bridge
        assert server.server_address[0] == "127.0.0.1"
