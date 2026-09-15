"""Audio features: fetching them, mapping energy to a DJ scale, and resolving
local tracks that have no Spotify ID to one that does.

No test here touches the network — ReccoBeats and Spotify search are stubbed.
"""

import pytest

from rbsync.features import (
    AudioFeatures,
    ReccoBeatsClient,
    energy_level,
    resolve_spotify_track,
)
from rbsync.models import LocalTrack, SpotifyTrack


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload


class RecordingTransport:
    """Serves queued responses and records every requested id batch."""

    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.batches: list[list[str]] = []

    def get(self, url: str, params: dict | None = None, **_):
        self.batches.append((params or {}).get("ids", "").split(","))
        return self.responses.pop(0)


def feature_row(spotify_id: str, isrc: str = "", energy: float = 0.5) -> dict:
    return {
        "id": f"recco-{spotify_id}",
        "href": f"https://open.spotify.com/track/{spotify_id}",
        "isrc": isrc,
        "energy": energy,
        "danceability": 0.6,
        "valence": 0.4,
        "tempo": 120.0,
        "key": 5,
        "mode": 1,
        "loudness": -7.5,
        "acousticness": 0.1,
        "instrumentalness": 0.8,
        "speechiness": 0.05,
        "liveness": 0.2,
    }


class TestEnergyLevel:
    @pytest.mark.parametrize(
        "energy, level",
        [(0.0, 1), (0.03, 1), (0.14, 1), (0.15, 2), (0.5, 5), (0.803, 8), (0.96, 10), (1.0, 10)],
    )
    def test_maps_zero_to_one_onto_one_to_ten(self, energy, level):
        assert energy_level(energy) == level

    def test_out_of_range_values_are_clamped(self):
        assert energy_level(-0.2) == 1
        assert energy_level(1.7) == 10


class TestFetching:
    def test_parses_every_field(self):
        transport = RecordingTransport([FakeResponse(200, {"content": [feature_row("sp1", "ISRC1", 0.803)]})])
        result = ReccoBeatsClient(transport=transport).audio_features(["sp1"])
        features = result["sp1"]
        assert isinstance(features, AudioFeatures)
        assert features.energy == pytest.approx(0.803)
        assert features.tempo == pytest.approx(120.0)
        assert features.key == 5
        assert features.energy_level == 8

    def test_batches_at_forty_ids(self):
        ids = [f"sp{i}" for i in range(85)]
        transport = RecordingTransport(
            [FakeResponse(200, {"content": []}) for _ in range(3)]
        )
        ReccoBeatsClient(transport=transport).audio_features(ids)
        assert [len(batch) for batch in transport.batches] == [40, 40, 5]

    def test_results_are_keyed_by_spotify_id_and_by_isrc(self):
        transport = RecordingTransport([FakeResponse(200, {"content": [feature_row("sp1", "ISRC1")]})])
        result = ReccoBeatsClient(transport=transport).audio_features(["ISRC1"])
        # An ISRC lookup must be retrievable by the ISRC that was asked for.
        assert "ISRC1" in result

    def test_ids_without_data_are_absent(self):
        transport = RecordingTransport([FakeResponse(200, {"content": [feature_row("sp1")]})])
        result = ReccoBeatsClient(transport=transport).audio_features(["sp1", "sp2"])
        assert "sp1" in result
        assert "sp2" not in result

    def test_empty_input_makes_no_request(self):
        transport = RecordingTransport([])
        assert ReccoBeatsClient(transport=transport).audio_features([]) == {}
        assert transport.batches == []

    def test_rate_limit_is_retried(self, monkeypatch):
        monkeypatch.setattr("rbsync.features.time.sleep", lambda _: None)
        transport = RecordingTransport([
            FakeResponse(429, headers={"Retry-After": "1"}),
            FakeResponse(200, {"content": [feature_row("sp1")]}),
        ])
        assert "sp1" in ReccoBeatsClient(transport=transport).audio_features(["sp1"])

    def test_a_failing_batch_does_not_lose_the_others(self):
        # One bad batch must not throw away features already fetched for the rest.
        ids = [f"sp{i}" for i in range(45)]
        transport = RecordingTransport([
            FakeResponse(200, {"content": [feature_row("sp0")]}),
            FakeResponse(500),
        ])
        result = ReccoBeatsClient(transport=transport).audio_features(ids)
        assert "sp0" in result

    def test_rows_missing_optional_fields_still_parse(self):
        row = {"href": "https://open.spotify.com/track/sp1", "energy": 0.4}
        transport = RecordingTransport([FakeResponse(200, {"content": [row]})])
        features = ReccoBeatsClient(transport=transport).audio_features(["sp1"])["sp1"]
        assert features.energy == pytest.approx(0.4)
        assert features.tempo is None

    def test_rows_without_energy_are_skipped(self):
        row = {"href": "https://open.spotify.com/track/sp1"}
        transport = RecordingTransport([FakeResponse(200, {"content": [row]})])
        assert ReccoBeatsClient(transport=transport).audio_features(["sp1"]) == {}


def spotify(id_, name, artist, seconds):
    return SpotifyTrack(id=id_, name=name, artists=[artist], album="",
                        duration_ms=int(seconds * 1000), isrc="", url="")


def local(title, artist, seconds, isrc=""):
    return LocalTrack(id="rb1", title=title, artist=artist, length_seconds=seconds, isrc=isrc)


class TestResolvingLocalTracks:
    """A rekordbox track has no Spotify ID; find the Spotify track that is it."""

    def test_picks_the_matching_track(self):
        hits = [spotify("wrong", "Versace (Remix)", "Migos", 250), spotify("right", "Versace", "Migos", 195)]
        found = resolve_spotify_track(local("Versace", "Migos", 195), lambda query: hits)
        assert found.id == "right"

    def test_prefers_the_closest_duration_among_equal_titles(self):
        hits = [spotify("radio", "Strobe", "Deadmau5", 200), spotify("full", "Strobe", "Deadmau5", 632)]
        found = resolve_spotify_track(local("Strobe", "Deadmau5", 630), lambda query: hits)
        assert found.id == "full"

    def test_messy_local_titles_still_resolve(self):
        hits = [spotify("sp", "Panda", "Desiigner", 245)]
        found = resolve_spotify_track(local("Panda (OFFICIAL SONG) Prod. By: Menace", "Desiigner", 246),
                                      lambda query: hits)
        assert found is not None and found.id == "sp"

    def test_wrong_artist_is_not_accepted(self):
        hits = [spotify("sp", "Closer", "The Chainsmokers", 240)]
        assert resolve_spotify_track(local("Closer", "Ne-Yo", 240), lambda query: hits) is None

    def test_no_hits_resolves_to_nothing(self):
        assert resolve_spotify_track(local("Versace", "Migos", 195), lambda query: []) is None

    def test_a_track_with_no_title_is_not_searched(self):
        calls = []
        resolve_spotify_track(local("", "Migos", 195), lambda query: calls.append(query) or [])
        assert calls == []

    def test_query_names_title_and_artist(self):
        queries = []
        resolve_spotify_track(local("Versace", "Migos", 195), lambda query: queries.append(query) or [])
        assert queries and "versace" in queries[0].lower() and "migos" in queries[0].lower()

    def test_falls_back_to_a_plain_word_search(self):
        hit = spotify("sp", "Keep Control - Extended Mix", "Sono", 420)
        found = resolve_spotify_track(
            local("Keep Control (Extended Mix)", "Sono", 420),
            lambda query: [] if query.startswith("track:") else [hit],
        )
        assert found is not None and found.id == "sp"

    def test_mixed_in_key_title_prefix_is_ignored(self):
        hits = [spotify("sp", "Shiko", "Gehlektek", 300)]
        found = resolve_spotify_track(local("1A - Energy 6 - Shiko", "Gehlektek", 300), lambda q: hits)
        assert found is not None

    def test_artist_repeated_in_title_is_ignored(self):
        queries = []
        hits = [spotify("sp", "Unstable Mind", "Red Scan", 300)]
        found = resolve_spotify_track(local("Red Scan - Unstable Mind", "Red Scan", 300),
                                      lambda q: queries.append(q) or hits)
        assert found is not None
        assert "red scan - " not in queries[0].lower()

    def test_query_drops_title_noise(self):
        queries = []
        resolve_spotify_track(local("Panda (Official Video)", "Desiigner", 245),
                              lambda query: queries.append(query) or [])
        assert "official" not in queries[0].lower()
