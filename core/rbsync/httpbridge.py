"""A localhost JSON-RPC bridge, for developing the UI in a browser.

The shipped app talks to this core over stdio as a Tauri sidecar. That is a
poor fit for iterating on the interface, because every change means rebuilding
a native bundle. This bridge exposes exactly the same RPC methods over HTTP so
``npm run dev`` in a browser can drive the real backend.

It is a development tool, never started by the packaged app:

* it binds to 127.0.0.1 only, so nothing outside this machine can reach it;
* it must be started explicitly with ``rbsync serve``.

Even so, it grants whatever can reach it the ability to write to the rekordbox
database, so it should not be left running.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .api import build_server

log = logging.getLogger(__name__)

DEFAULT_PORT = 8765


class _NullOut:
    """Swallows the stdio channel: HTTP replies are returned, not written."""

    def write(self, _data: str) -> None:
        return None

    def flush(self) -> None:
        return None


def _make_handler(rpc):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status: int, body: bytes, content_type="application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # The Vite dev server runs on a different port, so the browser
            # treats these as cross-origin requests.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802 - http.server naming
            self._send(204, b"")

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") in ("", "/health"):
                self._send(200, json.dumps({"ok": True}).encode())
                return
            self._send(404, json.dumps({"error": "not found"}).encode())

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/rpc":
                self._send(404, json.dumps({"error": "not found"}).encode())
                return
            length = int(self.headers.get("Content-Length") or 0)
            payload = self.rfile.read(length).decode("utf-8")
            response = rpc.handle_line(payload)
            self._send(200, (response or "{}").encode("utf-8"))

        def log_message(self, fmt: str, *args) -> None:
            log.debug("http %s", fmt % args)

    return Handler


def create_server(service=None, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    rpc = build_server(service, out=_NullOut())
    return ThreadingHTTPServer(("127.0.0.1", port), _make_handler(rpc))


def serve_in_background(service=None, port: int = DEFAULT_PORT):
    """Start the bridge on a daemon thread. Returns ``(server, thread)``."""
    server = create_server(service, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def serve(service=None, port: int = DEFAULT_PORT) -> None:
    server = create_server(service, port)
    host, bound_port = server.server_address[:2]
    print(f"rbsync dev bridge listening on http://{host}:{bound_port}/rpc")
    print("Development only - do not leave this running.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
