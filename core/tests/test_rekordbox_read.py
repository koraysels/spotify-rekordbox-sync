from rbsync.models import LocalTrack
from rbsync.rekordbox import RekordboxLibrary


class TestReadCollection:
    def test_loads_tracks(self, db_copy):
        with RekordboxLibrary.open(db_copy) as library:
            tracks = library.load_tracks()
        assert len(tracks) > 0
        assert all(isinstance(t, LocalTrack) for t in tracks)

    def test_tracks_carry_matching_fields(self, db_copy):
        with RekordboxLibrary.open(db_copy) as library:
            tracks = library.load_tracks()
        titled = [t for t in tracks if t.title]
        assert titled, "expected at least one titled track"
        sample = titled[0]
        assert sample.id
        assert isinstance(sample.length_seconds, float)

    def test_durations_are_seconds_not_milliseconds(self, db_copy):
        with RekordboxLibrary.open(db_copy) as library:
            tracks = library.load_tracks()
        playable = [t for t in tracks if t.length_seconds > 60]
        assert playable, "expected tracks longer than a minute"
        # A music library whose median track is over an hour means the units
        # were misread. This guards the ms/seconds boundary.
        median = sorted(t.length_seconds for t in playable)[len(playable) // 2]
        assert 60 < median < 1800

    def test_lists_playlists(self, db_copy):
        with RekordboxLibrary.open(db_copy) as library:
            playlists = library.list_playlists()
        assert isinstance(playlists, list)
        if playlists:
            assert playlists[0].id
            assert playlists[0].name is not None

    def test_close_is_idempotent(self, db_copy):
        library = RekordboxLibrary.open(db_copy)
        library.close()
        library.close()
