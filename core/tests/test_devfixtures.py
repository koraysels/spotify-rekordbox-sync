import pytest

from rbsync import devfixtures
from rbsync.matcher import TrackIndex
from rbsync.models import LocalTrack


class _Service:
    def __init__(self, tracks):
        self.index = TrackIndex(tracks)


@pytest.fixture
def service():
    tracks = [
        LocalTrack(id=str(i), title=f"Track {i}", artist=f"Artist {i}", length_seconds=180 + i)
        for i in range(60)
    ]
    return _Service(tracks)


class TestEnabled:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("RBSYNC_FAKE_SPOTIFY", raising=False)
        assert devfixtures.enabled() is False

    def test_enabled_by_env_var(self, monkeypatch):
        monkeypatch.setenv("RBSYNC_FAKE_SPOTIFY", "1")
        assert devfixtures.enabled() is True

    def test_other_values_do_not_enable(self, monkeypatch):
        monkeypatch.setenv("RBSYNC_FAKE_SPOTIFY", "yes")
        assert devfixtures.enabled() is False


class TestFakeClient:
    def test_lists_the_demo_playlists(self, service):
        client = devfixtures.build_fake_client(service)
        assert [p.id for p in client.list_playlists()] == [p[0] for p in devfixtures.FAKE_PLAYLISTS]

    def test_playlists_contain_tracks(self, service):
        client = devfixtures.build_fake_client(service)
        for playlist in client.list_playlists():
            assert client.playlist_tracks(playlist.id)

    def test_includes_tracks_that_are_not_owned(self, service):
        client = devfixtures.build_fake_client(service)
        names = {t.name for p in client.list_playlists() for t in client.playlist_tracks(p.id)}
        assert names & {title for title, _ in devfixtures.UNOWNED}

    def test_is_deterministic(self, service):
        first = devfixtures.build_fake_client(service)
        second = devfixtures.build_fake_client(service)
        assert [t.id for t in first.playlist_tracks("fake-peak")] == [
            t.id for t in second.playlist_tracks("fake-peak")
        ]

    def test_unknown_playlist_is_empty(self, service):
        assert devfixtures.build_fake_client(service).playlist_tracks("nope") == []


class TestIndexTracksProperty:
    def test_exposes_indexed_tracks(self):
        tracks = [LocalTrack(id="1", title="A", artist="B", length_seconds=100)]
        assert TrackIndex(tracks).tracks == tracks
