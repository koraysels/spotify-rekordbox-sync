import pytest

from rbsync.cache import Cache
from rbsync.matcher import Band, MatchConfig, TrackIndex
from rbsync.models import LocalTrack, SpotifyPlaylist, SpotifyTrack
from rbsync.sync import plan_playlist, wantlist_rows


@pytest.fixture
def cache(tmp_path):
    c = Cache(tmp_path / "cache.db")
    yield c
    c.close()


@pytest.fixture
def index():
    return TrackIndex([
        LocalTrack(id="rb1", title="Versace", artist="Migos", length_seconds=195),
        LocalTrack(id="rb2", title="Panda", artist="Desiigner", length_seconds=245),
    ])


def sp(id_, name, artist, ms, isrc=""):
    return SpotifyTrack(id=id_, name=name, artists=[artist], album="A",
                        duration_ms=ms, isrc=isrc, url=f"u/{id_}")


PLAYLIST = SpotifyPlaylist(id="pl1", name="Bangers", track_count=2)


class TestMatching:
    def test_confident_match_is_queued_for_adding(self, index, cache):
        plan = plan_playlist(PLAYLIST, [sp("s1", "Versace", "Migos", 195_000)], index, cache)
        assert plan.to_add == ["rb1"]
        assert plan.tracks[0].band is Band.ACCEPT

    def test_unmatched_track_is_missing(self, index, cache):
        plan = plan_playlist(PLAYLIST, [sp("s9", "Nothing Alike", "Nobody", 100_000)], index, cache)
        assert plan.to_add == []
        assert plan.tracks[0].band is Band.REJECT
        assert plan.tracks[0].content_id is None

    def test_coverage_counts_bands(self, index, cache):
        plan = plan_playlist(
            PLAYLIST,
            [sp("s1", "Versace", "Migos", 195_000), sp("s9", "Nope", "Nobody", 100_000)],
            index, cache,
        )
        assert plan.coverage.matched == 1
        assert plan.coverage.missing == 1
        assert plan.coverage.total == 2
        assert plan.coverage.percent == 50.0

    def test_empty_playlist_has_zero_coverage(self, index, cache):
        plan = plan_playlist(PLAYLIST, [], index, cache)
        assert plan.coverage.percent == 0.0
        assert plan.to_add == []


class TestCachedDecisions:
    def test_cached_accept_is_used_without_rematching(self, index, cache):
        cache.remember_decision("s5", "rb2", accepted=True)
        plan = plan_playlist(PLAYLIST, [sp("s5", "Unrecognisable", "Nobody", 999_000)], index, cache)
        assert plan.to_add == ["rb2"]
        assert plan.tracks[0].band is Band.ACCEPT
        assert plan.tracks[0].reason == "cached"

    def test_cached_reject_keeps_track_missing(self, index, cache):
        cache.remember_decision("s1", "rb1", accepted=False)
        plan = plan_playlist(PLAYLIST, [sp("s1", "Versace", "Migos", 195_000)], index, cache)
        assert plan.to_add == []
        assert plan.tracks[0].band is Band.REJECT
        assert plan.tracks[0].reason == "cached"


class TestReviewBand:
    def test_review_track_is_not_added_automatically(self, cache):
        index = TrackIndex([LocalTrack(id="rb1", title="Closer", artist="Ne-Yo", length_seconds=240)])
        plan = plan_playlist(
            PLAYLIST, [sp("s1", "Closer", "The Chainsmokers", 240_000)], index, cache
        )
        assert plan.tracks[0].band is Band.REVIEW
        assert plan.to_add == []
        assert plan.coverage.review == 1


class TestRemovals:
    def test_additive_by_default_keeps_unknown_tracks(self, index, cache):
        plan = plan_playlist(
            PLAYLIST, [sp("s1", "Versace", "Migos", 195_000)], index, cache,
            existing_content_ids=["rb2"],
        )
        assert plan.to_remove == []

    def test_removals_listed_when_enabled(self, index, cache):
        plan = plan_playlist(
            PLAYLIST, [sp("s1", "Versace", "Migos", 195_000)], index, cache,
            existing_content_ids=["rb2"], allow_removals=True,
        )
        assert plan.to_remove == ["rb2"]

    def test_removals_never_include_desired_tracks(self, index, cache):
        plan = plan_playlist(
            PLAYLIST, [sp("s1", "Versace", "Migos", 195_000)], index, cache,
            existing_content_ids=["rb1", "rb2"], allow_removals=True,
        )
        assert plan.to_remove == ["rb2"]

    def test_already_present_track_is_not_re_added(self, index, cache):
        plan = plan_playlist(
            PLAYLIST, [sp("s1", "Versace", "Migos", 195_000)], index, cache,
            existing_content_ids=["rb1"],
        )
        assert plan.to_add == []


class TestWantlist:
    def test_wantlist_contains_only_missing_tracks(self, index, cache):
        plan = plan_playlist(
            PLAYLIST,
            [sp("s1", "Versace", "Migos", 195_000), sp("s9", "Gone", "Ghost", 100_000, isrc="X1")],
            index, cache,
        )
        rows = wantlist_rows([plan])
        assert len(rows) == 1
        assert rows[0]["title"] == "Gone"
        assert rows[0]["playlist"] == "Bangers"
        assert rows[0]["isrc"] == "X1"

    def test_wantlist_deduplicates_across_playlists(self, index, cache):
        track = sp("s9", "Gone", "Ghost", 100_000)
        a = plan_playlist(PLAYLIST, [track], index, cache)
        b = plan_playlist(SpotifyPlaylist(id="pl2", name="Other", track_count=1), [track], index, cache)
        rows = wantlist_rows([a, b], deduplicate=True)
        assert len(rows) == 1


class TestConfigPassthrough:
    def test_strict_config_pushes_match_into_review(self, index, cache):
        plan = plan_playlist(
            PLAYLIST, [sp("s1", "Versace", "Migos", 195_000)], index, cache,
            config=MatchConfig(auto_accept=1.01, reject=0.2),
        )
        assert plan.tracks[0].band is Band.REVIEW
        assert plan.to_add == []
