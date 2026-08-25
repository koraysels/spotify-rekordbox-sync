import pytest

from rbsync.models import LocalTrack, SpotifyTrack
from rbsync.matcher import Band, MatchConfig, TrackIndex, match_track


def local(id_, title, artist, length, isrc=""):
    return LocalTrack(
        id=id_, title=title, artist=artist, length_seconds=length,
        isrc=isrc, folder_path=f"/music/{id_}.mp3", file_name=f"{id_}.mp3",
    )


def spotify(id_, name, artists, ms, isrc=""):
    return SpotifyTrack(
        id=id_, name=name, artists=list(artists), album="Album",
        duration_ms=ms, isrc=isrc, url=f"https://open.spotify.com/track/{id_}",
    )


@pytest.fixture
def config():
    return MatchConfig()


class TestExactMatching:
    def test_identical_artist_title_duration_auto_accepts(self, config):
        index = TrackIndex([local("1", "Versace", "Migos", 195)])
        result = match_track(spotify("s1", "Versace", ["Migos"], 195_000), index, config)
        assert result.band is Band.ACCEPT
        assert result.best.track.id == "1"

    def test_messy_local_title_still_matches(self, config):
        index = TrackIndex([local("1", "Panda (OFFICIAL SONG) Prod. By: Menace", "Designer", 293)])
        result = match_track(spotify("s1", "Panda", ["Desiigner"], 293_000), index, config)
        assert result.best is not None
        assert result.best.track.id == "1"

    def test_featured_artist_in_local_artist_field(self, config):
        index = TrackIndex([local("1", "Bake Sale (Original Version)", "Wiz Khalifa Ft. Travis Scott", 247)])
        result = match_track(
            spotify("s1", "Bake Sale (feat. Travis Scott)", ["Wiz Khalifa", "Travis Scott"], 247_000),
            index, config,
        )
        assert result.band is Band.ACCEPT

    def test_diacritics_do_not_block_match(self, config):
        index = TrackIndex([local("1", "Bruxelles arrive (feat. Caballero)", "Roméo Elvis", 217)])
        result = match_track(spotify("s1", "Bruxelles arrive", ["Romeo Elvis"], 217_000), index, config)
        assert result.band is Band.ACCEPT


class TestIsrc:
    def test_isrc_equality_forces_accept(self, config):
        index = TrackIndex([local("1", "Totally Different Title", "Someone Else", 400, isrc="USRC17607839")])
        result = match_track(
            spotify("s1", "Real Name", ["Real Artist"], 200_000, isrc="USRC17607839"), index, config
        )
        assert result.band is Band.ACCEPT
        assert result.best.score == 1.0
        assert result.best.reason == "isrc"

    def test_empty_isrc_does_not_match_empty_isrc(self, config):
        index = TrackIndex([local("1", "Some Track", "Some Artist", 200, isrc="")])
        result = match_track(spotify("s1", "Other Thing", ["Nobody"], 200_000, isrc=""), index, config)
        assert result.band is not Band.ACCEPT


class TestDurationGuard:
    def test_large_duration_delta_rejects_identical_title(self, config):
        index = TrackIndex([local("1", "Strobe", "Deadmau5", 640)])
        result = match_track(spotify("s1", "Strobe", ["Deadmau5"], 320_000), index, config)
        assert result.band is Band.REJECT

    def test_small_duration_delta_still_accepts(self, config):
        index = TrackIndex([local("1", "Strobe", "Deadmau5", 322)])
        result = match_track(spotify("s1", "Strobe", ["Deadmau5"], 320_000), index, config)
        assert result.band is Band.ACCEPT


class TestMixDescriptors:
    def test_radio_edit_never_auto_accepts_extended_mix(self, config):
        index = TrackIndex([local("1", "Titanium (Extended Mix)", "David Guetta", 300)])
        result = match_track(
            spotify("s1", "Titanium (Radio Edit)", ["David Guetta"], 300_000), index, config
        )
        assert result.band is not Band.ACCEPT

    def test_matching_remix_descriptors_accept(self, config):
        index = TrackIndex([local("1", "Strobe (Deadmau5 Remix)", "Deadmau5", 320)])
        result = match_track(
            spotify("s1", "Strobe (Deadmau5 Remix)", ["Deadmau5"], 320_000), index, config
        )
        assert result.band is Band.ACCEPT

    def test_original_not_confused_with_remix(self, config):
        index = TrackIndex([local("1", "Strobe (Some Guy Remix)", "Deadmau5", 320)])
        result = match_track(spotify("s1", "Strobe", ["Deadmau5"], 320_000), index, config)
        assert result.band is not Band.ACCEPT


class TestBanding:
    def test_no_candidates_is_reject(self, config):
        index = TrackIndex([local("1", "Nothing Alike", "Nobody", 100)])
        result = match_track(spotify("s1", "Versace", ["Migos"], 195_000), index, config)
        assert result.band is Band.REJECT
        assert result.best is None

    def test_thresholds_are_configurable(self):
        index = TrackIndex([local("1", "Versace", "Migos", 195)])
        track = spotify("s1", "Versace", ["Migos"], 195_000)
        strict = match_track(track, index, MatchConfig(auto_accept=1.01, reject=0.2))
        assert strict.band is Band.REVIEW

    def test_wrong_artist_same_title_lands_in_review_not_accept(self, config):
        index = TrackIndex([local("1", "Closer", "Ne-Yo", 240)])
        result = match_track(spotify("s1", "Closer", ["The Chainsmokers"], 240_000), index, config)
        assert result.band is not Band.ACCEPT


class TestIndexing:
    def test_index_prefilters_by_duration_bucket(self, config):
        tracks = [local(str(i), f"Song {i}", "Artist", 100 + i) for i in range(50)]
        tracks.append(local("target", "Versace", "Migos", 195))
        index = TrackIndex(tracks)
        candidates = index.search(spotify("s1", "Versace", ["Migos"], 195_000))
        assert any(c.track.id == "target" for c in candidates)
        assert len(candidates) < len(tracks)

    def test_candidates_sorted_by_score_descending(self, config):
        index = TrackIndex([
            local("1", "Versace", "Migos", 195),
            local("2", "Versace Nights", "Migos", 195),
        ])
        candidates = index.search(spotify("s1", "Versace", ["Migos"], 195_000))
        scores = [c.score for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_empty_index_returns_no_candidates(self, config):
        assert TrackIndex([]).search(spotify("s1", "X", ["Y"], 1000)) == []


class TestDuplicatePreference:
    def test_prefers_higher_bitrate_among_identical_copies(self, config):
        low = LocalTrack(id="low", title="Versace", artist="Migos", length_seconds=195, bit_rate=128)
        high = LocalTrack(id="high", title="Versace", artist="Migos", length_seconds=195, bit_rate=320)
        index = TrackIndex([low, high])
        result = match_track(spotify("s1", "Versace", ["Migos"], 195_000), index, config)
        assert result.best.track.id == "high"

    def test_prefers_analysed_copy_over_unanalysed(self, config):
        raw = LocalTrack(id="raw", title="Versace", artist="Migos", length_seconds=195, bit_rate=320, analysed=0)
        done = LocalTrack(id="done", title="Versace", artist="Migos", length_seconds=195, bit_rate=320, analysed=1)
        index = TrackIndex([raw, done])
        result = match_track(spotify("s1", "Versace", ["Migos"], 195_000), index, config)
        assert result.best.track.id == "done"

    def test_selection_is_stable_across_runs(self, config):
        tracks = [
            LocalTrack(id=str(i), title="Versace", artist="Migos", length_seconds=195, bit_rate=320)
            for i in range(5)
        ]
        picks = {
            TrackIndex(tracks).search(spotify("s1", "Versace", ["Migos"], 195_000))[0].track.id
            for _ in range(5)
        }
        assert len(picks) == 1
