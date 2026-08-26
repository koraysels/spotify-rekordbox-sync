import base64
import hashlib

import pytest

from rbsync.models import SpotifyPlaylist, SpotifyTrack
from rbsync.spotify import (
    SpotifyClient,
    Tokens,
    build_authorize_url,
    make_verifier,
    verifier_challenge,
)


class FakeTransport:
    """Serves canned pages so the client can be tested without the network."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url not in self.pages:
            raise AssertionError(f"unexpected url: {url}")
        return self.pages[url]


class TestPkce:
    def test_challenge_is_s256_of_verifier(self):
        verifier = "abc123"
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        assert verifier_challenge(verifier) == expected

    def test_challenge_has_no_padding(self):
        assert "=" not in verifier_challenge(make_verifier())

    def test_verifier_length_within_spec(self):
        verifier = make_verifier()
        assert 43 <= len(verifier) <= 128

    def test_verifiers_are_unique(self):
        assert make_verifier() != make_verifier()


class TestAuthorizeUrl:
    def test_contains_required_params(self):
        url = build_authorize_url("client123", "http://127.0.0.1:8888/callback", "verifier")
        assert "client_id=client123" in url
        assert "code_challenge_method=S256" in url
        assert "response_type=code" in url

    def test_requests_playlist_read_scopes(self):
        url = build_authorize_url("c", "http://127.0.0.1:8888/callback", "v")
        assert "playlist-read-private" in url
        assert "playlist-read-collaborative" in url


class TestPlaylistPaging:
    def test_follows_next_until_exhausted(self):
        page1 = {
            "items": [{"id": "p1", "name": "One", "items": {"total": 3},
                       "owner": {"display_name": "koray"}, "snapshot_id": "s1"}],
            "next": "https://api.spotify.com/v1/me/playlists?offset=1",
        }
        page2 = {
            "items": [{"id": "p2", "name": "Two", "items": {"total": 5},
                       "owner": {"display_name": "koray"}, "snapshot_id": "s2"}],
            "next": None,
        }
        transport = FakeTransport({
            "https://api.spotify.com/v1/me/playlists?limit=50": page1,
            "https://api.spotify.com/v1/me/playlists?offset=1": page2,
        })
        client = SpotifyClient(Tokens("tok", "ref", 9999), transport=transport)
        playlists = client.list_playlists()
        assert [p.id for p in playlists] == ["p1", "p2"]
        assert isinstance(playlists[0], SpotifyPlaylist)
        assert playlists[0].track_count == 3


class TestPlaylistTrackCount:
    """Spotify moved the playlist size from ``tracks.total`` to ``items.total``."""

    def _count(self, playlist):
        transport = FakeTransport({
            "https://api.spotify.com/v1/me/playlists?limit=50": {
                "items": [playlist], "next": None
            }
        })
        client = SpotifyClient(Tokens("tok", "ref", 9999), transport=transport)
        return client.list_playlists()[0].track_count

    def test_reads_items_total(self):
        assert self._count({"id": "p", "name": "N", "items": {"total": 7}}) == 7

    def test_falls_back_to_tracks_total(self):
        assert self._count({"id": "p", "name": "N", "tracks": {"total": 4}}) == 4

    def test_items_total_wins_when_both_present(self):
        assert self._count(
            {"id": "p", "name": "N", "items": {"total": 9}, "tracks": {"total": 4}}
        ) == 9

    def test_null_tracks_field_does_not_crash(self):
        # The live API returns ``"tracks": null`` alongside the new items field.
        assert self._count({"id": "p", "name": "N", "tracks": None, "items": {"total": 6}}) == 6

    def test_missing_both_is_zero(self):
        assert self._count({"id": "p", "name": "N"}) == 0


class TestTrackParsing:
    def _client(self, items, next_url=None):
        transport = FakeTransport({
            "https://api.spotify.com/v1/playlists/pl/items?limit=100": {
                "items": items, "next": next_url
            }
        })
        return SpotifyClient(Tokens("tok", "ref", 9999), transport=transport)

    def test_parses_track_fields(self):
        client = self._client([{
            "item": {
                "id": "t1", "name": "Versace", "duration_ms": 195000,
                "artists": [{"name": "Migos"}], "album": {"name": "YRN"},
                "external_ids": {"isrc": "USRC12345678"},
                "external_urls": {"spotify": "https://open.spotify.com/track/t1"},
                "type": "track", "is_local": False,
            }
        }])
        tracks = client.playlist_tracks("pl")
        assert len(tracks) == 1
        track = tracks[0]
        assert isinstance(track, SpotifyTrack)
        assert track.name == "Versace"
        assert track.artists == ["Migos"]
        assert track.duration_ms == 195000
        assert track.isrc == "USRC12345678"

    def test_skips_local_files(self):
        client = self._client([{
            "item": {"id": "t1", "name": "Local", "duration_ms": 1000,
                     "artists": [], "album": {"name": ""}, "type": "track", "is_local": True}
        }])
        assert client.playlist_tracks("pl") == []

    def test_skips_entries_marked_local_at_entry_level(self):
        client = self._client([{
            "is_local": True,
            "item": {"id": "t1", "name": "Local", "duration_ms": 1000,
                     "artists": [], "album": {"name": ""}, "type": "track"}
        }])
        assert client.playlist_tracks("pl") == []

    def test_still_accepts_the_legacy_track_key(self):
        client = self._client([{
            "track": {"id": "t1", "name": "Legacy", "duration_ms": 1000,
                      "artists": [{"name": "A"}], "album": {"name": "B"},
                      "type": "track", "is_local": False}
        }])
        assert client.playlist_tracks("pl")[0].name == "Legacy"

    def test_skips_podcast_episodes(self):
        client = self._client([{
            "item": {"id": "e1", "name": "Episode", "duration_ms": 1000,
                     "artists": [], "album": {"name": ""}, "type": "episode", "is_local": False}
        }])
        assert client.playlist_tracks("pl") == []

    def test_skips_null_tracks(self):
        client = self._client([{"item": None}])
        assert client.playlist_tracks("pl") == []

    def test_missing_isrc_becomes_empty_string(self):
        client = self._client([{
            "item": {"id": "t1", "name": "No ISRC", "duration_ms": 1000,
                      "artists": [{"name": "A"}], "album": {"name": "B"},
                      "type": "track", "is_local": False}
        }])
        assert client.playlist_tracks("pl")[0].isrc == ""

    def test_multiple_artists_preserved(self):
        client = self._client([{
            "item": {"id": "t1", "name": "Collab", "duration_ms": 1000,
                      "artists": [{"name": "A"}, {"name": "B"}],
                      "album": {"name": "C"}, "type": "track", "is_local": False}
        }])
        assert client.playlist_tracks("pl")[0].artists == ["A", "B"]


class TestTokenExpiry:
    def test_expired_token_is_detected(self):
        assert Tokens("tok", "ref", expires_at=0).expired is True

    def test_valid_token_is_not_expired(self):
        import time
        assert Tokens("tok", "ref", expires_at=time.time() + 3600).expired is False
