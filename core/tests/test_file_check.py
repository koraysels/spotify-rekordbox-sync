"""Verifying that matched rekordbox rows point at files that actually exist.

A playlist full of rows whose audio files are gone is worse than useless for a
DJ: rekordbox shows the track, and it will not play. The database can easily
reference files that were moved or deleted outside rekordbox.
"""

import pytest

from rbsync.app import AppService
from rbsync.cache import Cache
from rbsync.matcher import TrackIndex
from rbsync.models import LocalTrack


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
    present = tmp_path / "present.mp3"
    present.write_bytes(b"audio")

    svc = AppService(db_path=tmp_path / "none.db", cache=Cache(tmp_path / "cache.db"))
    svc._index = TrackIndex([
        LocalTrack(id="here", title="Here", artist="A", length_seconds=200,
                   folder_path=str(present), file_name="present.mp3"),
        LocalTrack(id="gone", title="Gone", artist="B", length_seconds=200,
                   folder_path=str(tmp_path / "missing.mp3"), file_name="missing.mp3"),
        LocalTrack(id="nopath", title="No path", artist="C", length_seconds=200),
    ])
    svc._track_count = 3
    yield svc
    svc.close()


class TestVolumeAwareness:
    """A file on an unplugged drive is not a missing file.

    Reporting "no file" for a track that lives on a disconnected external drive
    is wrong and alarming: nothing is lost, the drive is just not plugged in.
    """

    def test_path_on_an_unmounted_volume_is_offline(self, service, monkeypatch):
        from rbsync.matcher import TrackIndex

        service._index = TrackIndex([
            LocalTrack(id="ext", title="T", artist="A", length_seconds=200,
                       folder_path="/Volumes/NOT MOUNTED/music/t.mp3")
        ])
        result = service.verify_files(["ext"])["ext"]
        assert result["status"] == "offline"
        assert result["volume"] == "/Volumes/NOT MOUNTED"

    def test_offline_is_not_reported_as_existing(self, service):
        from rbsync.matcher import TrackIndex

        service._index = TrackIndex([
            LocalTrack(id="ext", title="T", artist="A", length_seconds=200,
                       folder_path="/Volumes/NOT MOUNTED/music/t.mp3")
        ])
        assert service.verify_files(["ext"])["ext"]["exists"] is False

    def test_missing_file_on_a_mounted_volume_is_missing(self, service):
        assert service.verify_files(["gone"])["gone"]["status"] == "missing"

    def test_present_file_status_is_ok(self, service):
        assert service.verify_files(["here"])["here"]["status"] == "ok"

    def test_row_without_a_path_is_unknown(self, service):
        assert service.verify_files(["nopath"])["nopath"]["status"] == "unknown"

    def test_a_mounted_volume_is_checked_normally(self, service, tmp_path, monkeypatch):
        from rbsync.matcher import TrackIndex

        volume = tmp_path / "Volumes" / "MOUNTED"
        (volume / "music").mkdir(parents=True)
        track_file = volume / "music" / "t.mp3"
        track_file.write_bytes(b"x")
        monkeypatch.setattr("rbsync.app.VOLUME_PREFIX", str(tmp_path / "Volumes"))
        service._index = TrackIndex([
            LocalTrack(id="ext", title="T", artist="A", length_seconds=200,
                       folder_path=str(track_file))
        ])
        assert service.verify_files(["ext"])["ext"]["status"] == "ok"


class TestVerify:
    def test_existing_file_is_reported_present(self, service):
        result = service.verify_files(["here"])
        assert result["here"]["exists"] is True

    def test_missing_file_is_reported_absent(self, service):
        result = service.verify_files(["gone"])
        assert result["gone"]["exists"] is False

    def test_row_without_a_path_is_absent(self, service):
        assert service.verify_files(["nopath"])["nopath"]["exists"] is False

    def test_reports_the_path_it_checked(self, service):
        assert service.verify_files(["gone"])["gone"]["path"].endswith("missing.mp3")

    def test_unknown_content_id_is_absent_not_an_error(self, service):
        assert service.verify_files(["nope"])["nope"]["exists"] is False

    def test_checks_many_at_once(self, service):
        result = service.verify_files(["here", "gone", "nopath"])
        assert set(result) == {"here", "gone", "nopath"}

    def test_empty_input_is_empty_output(self, service):
        assert service.verify_files([]) == {}

    def test_size_is_reported_for_existing_files(self, service):
        assert service.verify_files(["here"])["here"]["size"] == 5


class TestLibraryHealth:
    """A whole-collection view of what will actually play."""

    def test_counts_each_status(self, service):
        health = service.library_health()
        assert health["ok"] == 1
        assert health["missing"] == 1
        assert health["unknown"] == 1
        assert health["total"] == 3

    def test_groups_offline_tracks_by_volume(self, service):
        from rbsync.matcher import TrackIndex

        service._index = TrackIndex([
            LocalTrack(id="a", title="A", artist="A", length_seconds=1,
                       folder_path="/Volumes/BIG DRIVE/x.mp3"),
            LocalTrack(id="b", title="B", artist="B", length_seconds=1,
                       folder_path="/Volumes/BIG DRIVE/y.mp3"),
            LocalTrack(id="c", title="C", artist="C", length_seconds=1,
                       folder_path="/Volumes/OTHER/z.mp3"),
        ])
        health = service.library_health()
        assert health["offline"] == 3
        by_volume = {v["volume"]: v["count"] for v in health["volumes"]}
        assert by_volume == {"/Volumes/BIG DRIVE": 2, "/Volumes/OTHER": 1}

    def test_volumes_are_sorted_by_size(self, service):
        from rbsync.matcher import TrackIndex

        service._index = TrackIndex([
            LocalTrack(id="a", title="A", artist="A", length_seconds=1,
                       folder_path="/Volumes/SMALL/x.mp3"),
            LocalTrack(id="b", title="B", artist="B", length_seconds=1,
                       folder_path="/Volumes/BIG/y.mp3"),
            LocalTrack(id="c", title="C", artist="C", length_seconds=1,
                       folder_path="/Volumes/BIG/z.mp3"),
        ])
        assert service.library_health()["volumes"][0]["volume"] == "/Volumes/BIG"

    def test_empty_library_is_all_zero(self, service):
        from rbsync.matcher import TrackIndex

        service._index = TrackIndex([])
        health = service.library_health()
        assert health["total"] == 0
        assert health["volumes"] == []
