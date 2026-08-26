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


class TestWantlistText:
    def test_text_lines_are_artist_dash_title(self, index, cache):
        from rbsync.sync import wantlist_text

        plan = plan_playlist(PLAYLIST, [sp("s9", "Gone", "Ghost", 100_000)], index, cache)
        text = wantlist_text([plan])
        assert text == "Ghost - Gone"

    def test_text_has_one_line_per_track(self, index, cache):
        from rbsync.sync import wantlist_text

        plan = plan_playlist(
            PLAYLIST,
            [sp("s8", "Gone", "Ghost", 100_000), sp("s9", "Lost", "Phantom", 100_000)],
            index, cache,
        )
        assert len(wantlist_text([plan]).splitlines()) == 2

    def test_text_excludes_matched_tracks(self, index, cache):
        from rbsync.sync import wantlist_text

        plan = plan_playlist(
            PLAYLIST,
            [sp("s1", "Versace", "Migos", 195_000), sp("s9", "Gone", "Ghost", 100_000)],
            index, cache,
        )
        assert "Versace" not in wantlist_text([plan])

    def test_text_deduplicates(self, index, cache):
        from rbsync.sync import wantlist_text

        track = sp("s9", "Gone", "Ghost", 100_000)
        a = plan_playlist(PLAYLIST, [track], index, cache)
        b = plan_playlist(SpotifyPlaylist(id="p2", name="Other", track_count=1), [track], index, cache)
        assert len(wantlist_text([a, b]).splitlines()) == 1

    def test_empty_plan_is_empty_string(self, index, cache):
        from rbsync.sync import wantlist_text

        assert wantlist_text([plan_playlist(PLAYLIST, [], index, cache)]) == ""


class TestCachedAcceptKeepsCandidate:
    def test_cached_accept_reports_the_matched_local_track(self, index, cache):
        cache.remember_decision("s5", "rb2", accepted=True)
        plan = plan_playlist(PLAYLIST, [sp("s5", "Unrecognisable", "Nobody", 999_000)], index, cache)
        track_plan = plan.tracks[0]
        assert track_plan.candidates, "a cached accept must still name the local track"
        assert track_plan.candidates[0].track.id == "rb2"
        assert track_plan.candidates[0].reason == "cached"

    def test_cached_accept_for_an_unknown_id_has_no_candidate(self, index, cache):
        cache.remember_decision("s5", "gone-from-library", accepted=True)
        plan = plan_playlist(PLAYLIST, [sp("s5", "Whatever", "Nobody", 100_000)], index, cache)
        assert plan.tracks[0].candidates == []

    def test_cached_reject_has_no_candidate(self, index, cache):
        cache.remember_decision("s1", "rb1", accepted=False)
        plan = plan_playlist(PLAYLIST, [sp("s1", "Versace", "Migos", 195_000)], index, cache)
        assert plan.tracks[0].candidates == []


class TestWantlistDeduplication:
    def test_same_track_under_different_ids_is_listed_once(self, index, cache):
        from rbsync.sync import wantlist_text

        a = sp("id-one", "Unreleased Dub Plate", "Anonymous Producer", 210_000)
        b = sp("id-two", "Unreleased Dub Plate", "Anonymous Producer", 210_000)
        plan_a = plan_playlist(PLAYLIST, [a], index, cache)
        plan_b = plan_playlist(
            SpotifyPlaylist(id="pl2", name="Other", track_count=1), [b], index, cache
        )
        assert len(wantlist_text([plan_a, plan_b]).splitlines()) == 1

    def test_case_and_punctuation_differences_still_dedupe(self, index, cache):
        from rbsync.sync import wantlist_text

        a = sp("id-one", "Unreleased Dub Plate", "Anonymous Producer", 210_000)
        b = sp("id-two", "unreleased  dub plate!", "anonymous producer", 210_000)
        plan_a = plan_playlist(PLAYLIST, [a], index, cache)
        plan_b = plan_playlist(
            SpotifyPlaylist(id="pl2", name="Other", track_count=1), [b], index, cache
        )
        assert len(wantlist_text([plan_a, plan_b]).splitlines()) == 1

    def test_genuinely_different_tracks_are_both_listed(self, index, cache):
        from rbsync.sync import wantlist_text

        a = sp("id-one", "Track One", "Someone", 210_000)
        b = sp("id-two", "Track Two", "Someone", 210_000)
        plan = plan_playlist(PLAYLIST, [a, b], index, cache)
        assert len(wantlist_text([plan]).splitlines()) == 2


class TestChosenCandidateOverridesRanking:
    def test_plan_uses_the_chosen_copy_not_the_top_scorer(self, cache):
        # Two identical copies of one track: the matcher cannot tell them apart
        # on score, so the user's choice has to be what decides it.
        first = LocalTrack(id="copy-a", title="Versace", artist="Migos", length_seconds=195)
        second = LocalTrack(id="copy-b", title="Versace", artist="Migos", length_seconds=195)
        index = TrackIndex([first, second])
        track = sp("s1", "Versace", "Migos", 195_000)

        ranked = index.search(track)
        runner_up = ranked[1].track.id
        cache.remember_decision("s1", runner_up, accepted=True)

        plan = plan_playlist(PLAYLIST, [track], index, cache)
        assert plan.to_add == [runner_up]
        assert plan.tracks[0].content_id == runner_up

    def test_choosing_a_copy_survives_replanning(self, cache):
        first = LocalTrack(id="copy-a", title="Versace", artist="Migos", length_seconds=195)
        second = LocalTrack(id="copy-b", title="Versace", artist="Migos", length_seconds=195)
        index = TrackIndex([first, second])
        track = sp("s1", "Versace", "Migos", 195_000)
        cache.remember_decision("s1", "copy-b", accepted=True)

        for _ in range(3):
            plan = plan_playlist(PLAYLIST, [track], index, cache)
            assert plan.to_add == ["copy-b"]


class TestWantlistAttribution:
    def test_a_track_missing_in_several_playlists_names_them_all(self, index, cache):
        track = sp("m1", "Ghost Track", "Nobody", 200_000)
        a = plan_playlist(SpotifyPlaylist(id="pl1", name="Warm Up", track_count=1),
                          [track], index, cache)
        b = plan_playlist(SpotifyPlaylist(id="pl2", name="Peak Time", track_count=1),
                          [track], index, cache)
        rows = wantlist_rows([a, b], deduplicate=True)
        assert len(rows) == 1
        assert rows[0]["playlist"] == "Warm Up, Peak Time"

    def test_a_playlist_is_not_named_twice(self, index, cache):
        track = sp("m1", "Ghost Track", "Nobody", 200_000)
        same = sp("m2", "Ghost Track", "Nobody", 200_000)
        plan = plan_playlist(PLAYLIST, [track, same], index, cache)
        rows = wantlist_rows([plan], deduplicate=True)
        assert rows[0]["playlist"] == "Bangers"

    def test_single_playlist_attribution_is_unchanged(self, index, cache):
        plan = plan_playlist(PLAYLIST, [sp("m1", "Ghost", "Nobody", 200_000)], index, cache)
        assert wantlist_rows([plan], deduplicate=True)[0]["playlist"] == "Bangers"

    def test_without_dedup_each_playlist_keeps_its_own_row(self, index, cache):
        track = sp("m1", "Ghost Track", "Nobody", 200_000)
        a = plan_playlist(SpotifyPlaylist(id="pl1", name="Warm Up", track_count=1),
                          [track], index, cache)
        b = plan_playlist(SpotifyPlaylist(id="pl2", name="Peak Time", track_count=1),
                          [track], index, cache)
        rows = wantlist_rows([a, b], deduplicate=False)
        assert [r["playlist"] for r in rows] == ["Warm Up", "Peak Time"]
