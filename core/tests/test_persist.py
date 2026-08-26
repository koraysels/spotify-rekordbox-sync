"""Round-tripping a plan through storage must lose nothing that Apply needs."""

import pytest

from rbsync.cache import Cache
from rbsync.matcher import Band, TrackIndex
from rbsync.models import LocalTrack, SpotifyPlaylist, SpotifyTrack
from rbsync.persist import plan_from_json, plan_to_json
from rbsync.sync import plan_playlist


@pytest.fixture
def cache(tmp_path):
    c = Cache(tmp_path / "cache.db")
    yield c
    c.close()


@pytest.fixture
def plan(cache):
    index = TrackIndex([
        LocalTrack(id="rb1", title="Versace", artist="Migos", length_seconds=195,
                   isrc="I1", folder_path="/m/v.mp3", file_name="v.mp3",
                   bit_rate=320, file_size=999, analysed=1),
        LocalTrack(id="rb2", title="Versace", artist="Migos", length_seconds=195,
                   folder_path="/m/v2.mp3", file_name="v2.mp3", bit_rate=128),
    ])
    playlist = SpotifyPlaylist(id="pl1", name="Bangers", track_count=2, owner="koray",
                               snapshot_id="snap1", owner_id="me", collaborative=False)
    tracks = [
        SpotifyTrack(id="s1", name="Versace", artists=["Migos"], album="YRN",
                     duration_ms=195_000, isrc="I1", url="u1"),
        SpotifyTrack(id="s9", name="Gone", artists=["Ghost"], album="Nowhere",
                     duration_ms=400_000, isrc="", url="u9"),
    ]
    return plan_playlist(playlist, tracks, index, cache, existing_content_ids=["rb2"],
                         allow_removals=True)


class TestRoundTrip:
    def test_playlist_identity_survives(self, plan):
        restored = plan_from_json(plan_to_json(plan))
        assert restored.playlist == plan.playlist

    def test_write_lists_survive(self, plan):
        restored = plan_from_json(plan_to_json(plan))
        assert restored.to_add == plan.to_add
        assert restored.to_remove == plan.to_remove

    def test_coverage_survives(self, plan):
        restored = plan_from_json(plan_to_json(plan))
        assert restored.coverage.as_dict() == plan.coverage.as_dict()

    def test_track_plans_survive(self, plan):
        restored = plan_from_json(plan_to_json(plan))
        assert len(restored.tracks) == len(plan.tracks)
        for before, after in zip(plan.tracks, restored.tracks):
            assert after.track == before.track
            assert after.band == before.band
            assert after.content_id == before.content_id
            assert after.score == before.score

    def test_candidates_survive_in_full(self, plan):
        restored = plan_from_json(plan_to_json(plan))
        matched = next(t for t in restored.tracks if t.candidates)
        original = next(t for t in plan.tracks if t.candidates)
        assert [c.track for c in matched.candidates] == [c.track for c in original.candidates]
        assert matched.candidates[0].score == original.candidates[0].score

    def test_bands_are_enum_members_again(self, plan):
        restored = plan_from_json(plan_to_json(plan))
        assert all(isinstance(t.band, Band) for t in restored.tracks)

    def test_error_field_survives(self):
        from rbsync.sync import PlaylistPlan

        blocked = PlaylistPlan(
            playlist=SpotifyPlaylist(id="p", name="N", track_count=0),
            error="Spotify will not share this playlist.",
        )
        assert plan_from_json(plan_to_json(blocked)).error == blocked.error

    def test_json_is_serialisable(self, plan):
        import json

        json.dumps(plan_to_json(plan))


class TestStorage:
    def test_saved_plan_reads_back(self, cache, plan):
        cache.save_plan("pl1", snapshot_id="snap1", fingerprint="fp1",
                        payload=plan_to_json(plan))
        stored = cache.get_plan("pl1")
        assert stored.snapshot_id == "snap1"
        assert stored.fingerprint == "fp1"
        assert plan_from_json(stored.payload).to_add == plan.to_add

    def test_unknown_playlist_has_no_plan(self, cache):
        assert cache.get_plan("nope") is None

    def test_saving_again_replaces(self, cache, plan):
        cache.save_plan("pl1", snapshot_id="a", fingerprint="f", payload=plan_to_json(plan))
        cache.save_plan("pl1", snapshot_id="b", fingerprint="f", payload=plan_to_json(plan))
        assert cache.get_plan("pl1").snapshot_id == "b"

    def test_plan_survives_reopen(self, tmp_path, plan):
        path = tmp_path / "c.db"
        first = Cache(path)
        first.save_plan("pl1", snapshot_id="s", fingerprint="f", payload=plan_to_json(plan))
        first.close()
        second = Cache(path)
        assert second.get_plan("pl1") is not None
        second.close()

    def test_clearing_removes_all_plans(self, cache, plan):
        cache.save_plan("pl1", snapshot_id="s", fingerprint="f", payload=plan_to_json(plan))
        cache.clear_plans()
        assert cache.get_plan("pl1") is None

    def test_deleting_one_plan(self, cache, plan):
        cache.save_plan("pl1", snapshot_id="s", fingerprint="f", payload=plan_to_json(plan))
        cache.save_plan("pl2", snapshot_id="s", fingerprint="f", payload=plan_to_json(plan))
        cache.delete_plan("pl1")
        assert cache.get_plan("pl1") is None
        assert cache.get_plan("pl2") is not None
