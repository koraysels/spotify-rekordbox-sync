"""Line-delimited JSON-RPC 2.0 over stdio.

The Tauri shell spawns this as a sidecar and talks to it on stdin/stdout. Two
properties matter more than elegance here:

* A handler that raises must produce an error object, never a dead process.
  If the sidecar dies the UI has no way to explain what happened.
* Long operations must report progress as notifications, because loading a
  12,000-track library and matching hundreds of tracks is not instant and a
  frozen window reads as a crash.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from typing import Any, Callable

log = logging.getLogger(__name__)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32000


class RpcServer:
    def __init__(self, service: Any, out=None) -> None:
        self.service = service
        self._out = out or sys.stdout
        self._methods: dict[str, Callable[..., Any]] = {}
        self.register("ping", lambda **_: {"pong": True})

    def register(self, name: str, handler: Callable[..., Any]) -> None:
        self._methods[name] = handler

    def emit(self, raw: str) -> None:
        self._out.write(raw + "\n")
        self._out.flush()

    def notify(self, method: str, params: dict | None = None) -> None:
        """Send a server-initiated message. Notifications carry no id."""
        self.emit(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}))

    def progress(self, message: str, **extra) -> None:
        self.notify("progress", {"message": message, **extra})

    def handle_line(self, line: str) -> str | None:
        line = (line or "").strip()
        if not line:
            return None

        try:
            request = json.loads(line)
        except ValueError as exc:
            return self._error(None, PARSE_ERROR, f"invalid JSON: {exc}")

        if not isinstance(request, dict):
            return self._error(None, INVALID_REQUEST, "request must be an object")

        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        if not isinstance(method, str):
            return self._error(request_id, INVALID_REQUEST, "missing method")

        handler = self._methods.get(method)
        if handler is None:
            # A notification gets no reply even when it is wrong.
            if request_id is None:
                return None
            return self._error(request_id, METHOD_NOT_FOUND, f"unknown method: {method}")

        try:
            result = handler(**params) if isinstance(params, dict) else handler(*params)
        except Exception as exc:  # noqa: BLE001 - the whole point is not to die
            log.exception("rpc handler failed: %s", method)
            if request_id is None:
                return None
            return self._error(
                request_id, INTERNAL_ERROR, str(exc) or exc.__class__.__name__,
                data={"type": exc.__class__.__name__, "traceback": traceback.format_exc()},
            )

        if request_id is None:
            return None
        return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _error(self, request_id, code: int, message: str, data: dict | None = None) -> str:
        error: dict[str, Any] = {"code": code, "message": message}
        if data:
            error["data"] = data
        return json.dumps({"jsonrpc": "2.0", "id": request_id, "error": error})

    def serve_forever(self, stream=None) -> None:
        stream = stream or sys.stdin
        for line in stream:
            response = self.handle_line(line)
            if response:
                self.emit(response)
