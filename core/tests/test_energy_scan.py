"""The rekordbox-playlist energy scan, against a library copy with the network stubbed."""

import pytest

from rbsync import app as app_module
from rbsync.app import AppService
from rbsync.cache import Cache
from rbsync.features import AudioFeatures
from rbsync.models import SpotifyTrack
from rbsync.rekordbox import RekordboxLibrary


class FakeRecco:
    calls: list[list[str]] = []

    def audio_features(self, ids):
        FakeRecco.calls.append(list(ids))
        return {i: AudioFeatures(energy=0.72) for i in ids}

    def close(self):
        pass


class FakeSpotify:
    searches = 0

    def search_tracks(self, query):
        FakeSpotify.searches += 1
        return self._hits

    def close(self):
        pass


@pytest.fixture
def service(db_copy, tmp_path, monkeypatch, rekordbox_closed):
    FakeRecco.calls = []
    FakeSpotify.searches = 0
    monkeypatch.setattr(app_module, "ReccoBeatsClient", FakeRecco)
    svc = AppService(db_path=db_copy, cache=Cache(tmp_path / "cache.db"))
    yield svc
    svc.close()


def _playlist_with_tracks(db_copy):
    with RekordboxLibrary.open(db_copy) as library:
        for node in library.playlist_tree():
            if not node["isFolder"] and 1 <= node["trackCount"] <= 40:
                return node["id"]
    pytest.skip("no small playlist in the fixture library")


def _spotify_mirroring(service):
    """Search that returns each queried track as itself, so it resolves."""
    fake = FakeSpotify()

    def search(query):
        FakeSpotify.searches += 1
        for track in service.index.tracks:
            if track.title and track.title.lower()[:20] in query.lower():
                return [SpotifyTrack(id=f"sp-{track.id}", name=track.title,
                                     artists=[track.artist or "x"], album="",
                                     duration_ms=int(track.length_seconds * 1000))]
        return []

    fake.search_tracks = search
    return fake


def test_scan_reports_every_track_with_a_status(service, db_copy, monkeypatch):
    playlist = _playlist_with_tracks(db_copy)
    monkeypatch.setattr(service, "spotify", lambda: _spotify_mirroring(service))
    result = service.scan_energy([playlist])
    assert result["tracks"]
    assert {row["status"] for row in result["tracks"]} <= {"ready", "tagged", "unresolved", "no-data", "pending"}
    assert any(row["energyLevel"] == 7 for row in result["tracks"])


def test_second_scan_makes_no_network_calls(service, db_copy, monkeypatch):
    playlist = _playlist_with_tracks(db_copy)
    monkeypatch.setattr(service, "spotify", lambda: _spotify_mirroring(service))
    service.scan_energy([playlist])
    searches, fetches = FakeSpotify.searches, len(FakeRecco.calls)
    service.scan_energy([playlist])
    assert FakeSpotify.searches == searches
    assert len(FakeRecco.calls) == fetches


def test_scan_without_spotify_still_returns_rows(service, db_copy, monkeypatch):
    playlist = _playlist_with_tracks(db_copy)

    def not_connected():
        raise RuntimeError("Not connected to Spotify")

    monkeypatch.setattr(service, "spotify", not_connected)
    result = service.scan_energy([playlist])
    assert result["tracks"]
    assert "Not connected" in result["searchError"]


def test_apply_then_rescan_shows_tagged(service, db_copy, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module.paths, "backups_dir", lambda: tmp_path / "backups")
    playlist = _playlist_with_tracks(db_copy)
    monkeypatch.setattr(service, "spotify", lambda: _spotify_mirroring(service))
    rows = [r for r in service.scan_energy([playlist])["tracks"] if r["status"] == "ready"]
    if not rows:
        pytest.skip("nothing resolvable in this playlist")
    result = service.apply_energy({r["contentId"]: r["energyLevel"] for r in rows})
    assert result["changed"] == len(rows)
    again = {r["contentId"]: r["status"] for r in service.scan_energy([playlist])["tracks"]}
    assert all(again[r["contentId"]] == "tagged" for r in rows)
