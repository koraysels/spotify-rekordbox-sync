import json
import os

import pytest

from rbsync.api import build_server
from rbsync.app import AppService
from rbsync.cache import Cache
from rbsync.matcher import MatchCandidate
from rbsync.models import LocalTrack
from rbsync.persist import _local_track_from_json, _local_track_to_json
from rbsync.serialize import candidate_to_dict


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


def test_downloader_defaults(server):
    s = call(server, "settings.get")["result"]
    assert s["downloaderEnabled"] is False
    assert s["downloadFolder"].endswith(os.path.join("Downloads", "rbsync"))
    assert s["hasDownloaderSecret"] is False
    assert s["spotdlPath"] == ""


def test_secret_is_write_only(server):
    call(server, "settings.set", {"downloaderClientId": "id", "downloaderClientSecret": "s3cret"})
    s = call(server, "settings.get")["result"]
    assert s["hasDownloaderSecret"] is True and "s3cret" not in json.dumps(s)
    assert s["downloaderClientId"] == "id"
    call(server, "settings.set", {"downloaderClientSecret": ""})
    assert call(server, "settings.get")["result"]["hasDownloaderSecret"] is False


def test_enqueue_refused_when_disabled(server):
    r = call(server, "downloader.enqueue", {"tracks": [], "playlistName": "x"})
    assert "switched off" in r["error"]["message"]


def test_status_shape(server, tmp_path):
    r = call(server, "downloader.status")["result"]
    assert r["enabled"] is False and r["version"] == "4.6.0"
    assert set(r["spotdl"]) == {"path", "source"}
    assert r["paused"] is False and r["jobs"] == []


def test_resume_and_cancel(server):
    assert call(server, "downloader.resume")["result"] == {"paused": False}
    assert call(server, "downloader.cancel")["result"] == {"cancelled": 0}


def test_downloads_get_reports_existence(server, service, tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    service.cache.record_download("sp1", status="done", path=str(f))
    service.cache.record_download("sp2", status="done", path=str(tmp_path / "gone.mp3"))
    r = call(server, "downloads.get", {"spotifyIds": ["sp1", "sp2"]})["result"]
    assert r["sp1"]["exists"] is True and r["sp2"]["exists"] is False
    assert r["sp1"]["status"] == "done"


def test_candidate_carries_comment():
    c = MatchCandidate(track=LocalTrack(id="1", title="t", artist="a", length_seconds=1.0, comment="lowq"), score=0.9)
    assert candidate_to_dict(c)["comment"] == "lowq"


def test_stored_plan_without_comment_still_loads():
    data = _local_track_to_json(LocalTrack(id="1", title="t", artist="a", length_seconds=1.0, comment="lowq"))
    assert data["comment"] == "lowq"
    del data["comment"]
    assert _local_track_from_json(data).comment == ""
