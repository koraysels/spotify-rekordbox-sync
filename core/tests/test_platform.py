"""Behaviour that differs between macOS and Windows.

The app ships on both, and the two disagree about where rekordbox keeps its
database and what "the drive is not plugged in" looks like.
"""

import pytest

from rbsync.app import AppService
from rbsync.cache import Cache
from rbsync.matcher import TrackIndex
from rbsync.models import LocalTrack


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
    svc = AppService(db_path=tmp_path / "none.db", cache=Cache(tmp_path / "cache.db"))
    yield svc
    svc.close()


class TestVolumeDetectionOnMac:
    def test_external_volume_is_recognised(self, service, monkeypatch):
        monkeypatch.setattr("rbsync.app.IS_WINDOWS", False)
        assert service._volume_of("/Volumes/BIG DRIVE/music/t.mp3") == "/Volumes/BIG DRIVE"

    def test_internal_path_has_no_volume(self, service, monkeypatch):
        monkeypatch.setattr("rbsync.app.IS_WINDOWS", False)
        assert service._volume_of("/Users/koray/Music/t.mp3") == ""


class TestVolumeDetectionOnWindows:
    """On Windows a path's volume is its drive; an unplugged drive is a drive
    letter that no longer resolves."""

    def test_drive_letter_is_the_volume(self, service, monkeypatch):
        monkeypatch.setattr("rbsync.app.IS_WINDOWS", True)
        assert service._volume_of(r"D:\Music\track.mp3") == "D:\\"

    def test_forward_slashes_are_handled(self, service, monkeypatch):
        monkeypatch.setattr("rbsync.app.IS_WINDOWS", True)
        assert service._volume_of("E:/Music/track.mp3") == "E:\\"

    def test_unc_share_is_a_volume(self, service, monkeypatch):
        monkeypatch.setattr("rbsync.app.IS_WINDOWS", True)
        assert service._volume_of(r"\\nas\music\track.mp3").startswith("\\\\")

    def test_relative_path_has_no_volume(self, service, monkeypatch):
        monkeypatch.setattr("rbsync.app.IS_WINDOWS", True)
        assert service._volume_of("music/track.mp3") == ""


class TestFileStatusUsesTheVolume:
    def test_missing_windows_drive_reports_offline(self, service, monkeypatch):
        monkeypatch.setattr("rbsync.app.IS_WINDOWS", True)
        service._index = TrackIndex([
            LocalTrack(id="x", title="T", artist="A", length_seconds=100,
                       folder_path=r"Z:\music\gone.mp3")
        ])
        result = service.verify_files(["x"])["x"]
        assert result["status"] == "offline"
        assert result["volume"] == "Z:\\"


class TestDatabaseLocation:
    def test_windows_fallback_is_the_roaming_profile(self, tmp_path, monkeypatch):
        from rbsync import rekordbox

        appdata = tmp_path / "AppData" / "Roaming"
        target = appdata / "Pioneer" / "rekordbox" / "master.db"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"db")

        monkeypatch.setattr(rekordbox, "IS_WINDOWS", True)
        monkeypatch.setenv("APPDATA", str(appdata))
        # pyrekordbox's own config lookup finds nothing in the test environment.
        monkeypatch.setattr(rekordbox, "get_config", lambda *a, **k: None)
        assert rekordbox.default_database_path() == target

    def test_mac_fallback_is_the_pioneer_folder(self, tmp_path, monkeypatch):
        from rbsync import rekordbox

        home = tmp_path / "home"
        target = home / "Library" / "Pioneer" / "rekordbox" / "master.db"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"db")

        monkeypatch.setattr(rekordbox, "IS_WINDOWS", False)
        monkeypatch.setattr(rekordbox.Path, "home", classmethod(lambda cls: home))
        monkeypatch.setattr(rekordbox, "get_config", lambda *a, **k: None)
        assert rekordbox.default_database_path() == target
