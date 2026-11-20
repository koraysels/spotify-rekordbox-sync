import io
import json
import threading

from rbsync.rpc import RpcServer


def test_concurrent_notifications_stay_line_intact():
    out = io.StringIO()
    server = RpcServer(service=None, out=out)
    threads = [
        threading.Thread(
            target=lambda: [server.notify("x", {"n": "y" * 200}) for _ in range(300)]
        )
        for _ in range(4)
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    lines = out.getvalue().splitlines()
    assert len(lines) == 1200 and all(json.loads(l)["method"] == "x" for l in lines)


def test_serve_forever_runs_closers_on_eof():
    server = RpcServer(service=None, out=io.StringIO())
    called = []
    server.add_closer(lambda: called.append(1))
    server.serve_forever(io.StringIO(""))
    assert called == [1]


def test_close_runs_closers_once_and_swallows_errors():
    server = RpcServer(service=None, out=io.StringIO())
    called = []

    def boom():
        raise RuntimeError("nope")

    server.add_closer(boom)
    server.add_closer(lambda: called.append(1))
    server.close()
    server.close()
    assert called == [1]
