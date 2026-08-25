import csv

import pytest

from rbsync.app import AppService
from rbsync.cache import Cache
from rbsync.matcher import TrackIndex
from rbsync.models import LocalTrack, SpotifyPlaylist, SpotifyTrack
from rbsync.sync import SyncPlan, plan_playlist


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
    svc = AppService(db_path=tmp_path / "none.db", cache=Cache(tmp_path / "cache.db"))
    yield svc
    svc.close()


@pytest.fixture
def plan(service):
    index = TrackIndex([LocalTrack(id="rb1", title="Versace", artist="Migos", length_seconds=195)])
    playlist = SpotifyPlaylist(id="pl1", name="Bangers", track_count=2)
    tracks = [
        SpotifyTrack(id="s1", name="Versace", artists=["Migos"], album="YRN",
                     duration_ms=195_000, isrc="", url="u1"),
        SpotifyTrack(id="s9", name="Gone", artists=["Ghost"], album="Nowhere",
                     duration_ms=200_000, isrc="X1", url="u9"),
    ]
    return SyncPlan(playlists=[plan_playlist(playlist, tracks, index, service.cache)])


class TestCsvExport:
    def test_writes_csv_with_header(self, service, plan, tmp_path):
        target = service.export_wantlist(plan, tmp_path / "want.csv")
        rows = list(csv.DictReader(target.open()))
        assert len(rows) == 1
        assert rows[0]["title"] == "Gone"
        assert rows[0]["isrc"] == "X1"

    def test_csv_excludes_matched_tracks(self, service, plan, tmp_path):
        target = service.export_wantlist(plan, tmp_path / "want.csv")
        assert "Versace" not in target.read_text()


class TestTextExport:
    def test_writes_plain_text_lines(self, service, plan, tmp_path):
        target = service.export_wantlist(plan, tmp_path / "want.txt", fmt="txt")
        assert target.read_text().strip() == "Ghost - Gone"

    def test_text_format_infers_from_extension(self, service, plan, tmp_path):
        target = service.export_wantlist(plan, tmp_path / "want.txt")
        assert "," not in target.read_text()

    def test_unknown_format_raises(self, service, plan, tmp_path):
        with pytest.raises(ValueError):
            service.export_wantlist(plan, tmp_path / "want.xml", fmt="xml")


class TestDefaultLocation:
    def test_defaults_into_exports_dir(self, service, plan):
        target = service.export_wantlist(plan)
        assert target.parent.name == "exports"
        assert target.suffix == ".csv"
