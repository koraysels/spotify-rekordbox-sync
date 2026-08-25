from rbsync.cache import Cache
from rbsync.matcher import Band, TrackIndex
from rbsync.models import LocalTrack, SpotifyPlaylist, SpotifyTrack
from rbsync.serialize import (
    candidate_to_dict,
    playlist_plan_to_dict,
    sync_plan_to_dict,
    track_to_dict,
)
from rbsync.sync import SyncPlan, plan_playlist

import pytest


@pytest.fixture
def cache(tmp_path):
    c = Cache(tmp_path / "cache.db")
    yield c
    c.close()


@pytest.fixture
def plan(cache):
    index = TrackIndex([
        LocalTrack(id="rb1", title="Versace", artist="Migos", length_seconds=195,
                   folder_path="/music/versace.mp3", file_name="versace.mp3", bit_rate=320),
    ])
    playlist = SpotifyPlaylist(id="pl1", name="Bangers", track_count=2, owner="koray")
    tracks = [
        SpotifyTrack(id="s1", name="Versace", artists=["Migos"], album="YRN",
                     duration_ms=195_000, isrc="", url="u1"),
        SpotifyTrack(id="s9", name="Gone", artists=["Ghost"], album="Nowhere",
                     duration_ms=400_000, isrc="X1", url="u9"),
    ]
    return plan_playlist(playlist, tracks, index, cache)


class TestTrackSerialization:
    def test_uses_camel_case_for_the_ui(self):
        track = SpotifyTrack(id="s1", name="A", artists=["B"], album="C",
                             duration_ms=1000, isrc="I", url="U")
        payload = track_to_dict(track)
        assert payload["durationMs"] == 1000
        assert "duration_ms" not in payload

    def test_artists_are_a_list_copy(self):
        artists = ["A", "B"]
        payload = track_to_dict(
            SpotifyTrack(id="s", name="n", artists=artists, album="", duration_ms=0)
        )
        payload["artists"].append("C")
        assert artists == ["A", "B"]

    def test_display_is_included(self):
        payload = track_to_dict(
            SpotifyTrack(id="s", name="Versace", artists=["Migos"], album="", duration_ms=0)
        )
        assert payload["display"] == "Migos - Versace"


class TestPlanSerialization:
    def test_playlist_plan_is_json_safe(self, plan):
        import json

        json.dumps(playlist_plan_to_dict(plan))

    def test_coverage_is_expanded(self, plan):
        payload = playlist_plan_to_dict(plan)
        assert payload["coverage"]["total"] == 2
        assert payload["coverage"]["percent"] == 50.0

    def test_bands_serialize_as_strings(self, plan):
        payload = playlist_plan_to_dict(plan)
        assert all(isinstance(track["band"], str) for track in payload["tracks"])
        assert payload["tracks"][0]["band"] == Band.ACCEPT.value

    def test_add_and_remove_lists_are_present(self, plan):
        payload = playlist_plan_to_dict(plan)
        assert payload["toAdd"] == ["rb1"]
        assert payload["toRemove"] == []

    def test_sync_plan_aggregates_coverage(self, plan):
        payload = sync_plan_to_dict(SyncPlan(playlists=[plan, plan]))
        assert payload["coverage"]["total"] == 4
        assert len(payload["playlists"]) == 2


class TestCandidateSerialization:
    def test_candidate_exposes_file_location(self, plan):
        matched = [t for t in plan.tracks if t.candidates]
        assert matched, "expected at least one candidate"
        payload = candidate_to_dict(matched[0].candidates[0])
        assert payload["folderPath"] == "/music/versace.mp3"
        assert payload["bitRate"] == 320
        assert 0.0 <= payload["score"] <= 1.0

    def test_component_scores_are_exposed(self, plan):
        matched = [t for t in plan.tracks if t.candidates][0]
        payload = candidate_to_dict(matched.candidates[0])
        for key in ("titleScore", "artistScore", "durationScore"):
            assert key in payload
