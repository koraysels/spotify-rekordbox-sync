import json

import pytest

from rbsync.rpc import RpcServer


@pytest.fixture
def server():
    return RpcServer(service=object())


def call(server, payload):
    line = json.dumps(payload)
    raw = server.handle_line(line)
    return json.loads(raw) if raw else None


class TestProtocol:
    def test_ping_echoes_id(self, server):
        response = call(server, {"jsonrpc": "2.0", "id": 7, "method": "ping"})
        assert response["id"] == 7
        assert response["result"]["pong"] is True

    def test_response_declares_jsonrpc_version(self, server):
        response = call(server, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert response["jsonrpc"] == "2.0"

    def test_unknown_method_returns_method_not_found(self, server):
        response = call(server, {"jsonrpc": "2.0", "id": 2, "method": "nope"})
        assert response["error"]["code"] == -32601

    def test_malformed_json_returns_parse_error(self, server):
        response = json.loads(server.handle_line("{not json"))
        assert response["error"]["code"] == -32700

    def test_notification_gets_no_response(self, server):
        assert server.handle_line(json.dumps({"jsonrpc": "2.0", "method": "ping"})) is None

    def test_blank_line_is_ignored(self, server):
        assert server.handle_line("   ") is None


class TestErrorHandling:
    def test_handler_exception_becomes_error_not_crash(self, server):
        def boom(**_):
            raise ValueError("kaboom")

        server.register("explode", boom)
        response = call(server, {"jsonrpc": "2.0", "id": 3, "method": "explode"})
        assert response["error"]["code"] == -32000
        assert "kaboom" in response["error"]["message"]

    def test_error_carries_exception_type(self, server):
        def boom(**_):
            raise ValueError("kaboom")

        server.register("explode", boom)
        response = call(server, {"jsonrpc": "2.0", "id": 3, "method": "explode"})
        assert response["error"]["data"]["type"] == "ValueError"

    def test_server_survives_after_handler_error(self, server):
        def boom(**_):
            raise ValueError("kaboom")

        server.register("explode", boom)
        call(server, {"jsonrpc": "2.0", "id": 3, "method": "explode"})
        assert call(server, {"jsonrpc": "2.0", "id": 4, "method": "ping"})["result"]["pong"] is True


class TestParams:
    def test_params_are_passed_as_keywords(self, server):
        server.register("echo", lambda **kw: kw)
        response = call(server, {"jsonrpc": "2.0", "id": 5, "method": "echo",
                                 "params": {"a": 1, "b": "two"}})
        assert response["result"] == {"a": 1, "b": "two"}

    def test_missing_params_is_empty_dict(self, server):
        server.register("echo", lambda **kw: kw)
        response = call(server, {"jsonrpc": "2.0", "id": 6, "method": "echo"})
        assert response["result"] == {}


class TestProgress:
    def test_progress_notification_has_no_id(self, server):
        sent = []
        server.emit = sent.append
        server.notify("progress", {"message": "working"})
        payload = json.loads(sent[0])
        assert "id" not in payload
        assert payload["method"] == "progress"
        assert payload["params"]["message"] == "working"
