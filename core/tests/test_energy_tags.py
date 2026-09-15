"""Energy My Tags written to a copy of a real library."""

import pytest

from rbsync.rekordbox import (
    RekordboxLibrary,
    comment_energy,
    parse_energy_tag,
)


class TestParsing:
    @pytest.mark.parametrize("comment, level", [
        ("9A - Energy 6", 6), ("6A - Energy 7 - GloryBeats.com", 7), ("energy 10", 10),
        ("", None), ("Energy 0", None), ("Energy 12", None), ("synergy", None),
    ])
    def test_mixed_in_key_comments(self, comment, level):
        assert comment_energy(comment) == level

    def test_tag_names(self):
        assert parse_energy_tag("Energy 8") == 8
        assert parse_energy_tag("My Comment") is None
        assert parse_energy_tag("Energy 8 extra") is None


@pytest.fixture
def library(db_copy, rekordbox_closed):
    lib = RekordboxLibrary.open(db_copy)
    yield lib
    lib.close()


@pytest.fixture
def ids(library):
    tracks = [t for t in library.load_tracks() if t.title][:3]
    return [t.id for t in tracks]


class TestLoadTracks:
    def test_bpm_is_real_beats_per_minute(self, library):
        bpms = [t.bpm for t in library.load_tracks() if t.bpm]
        assert bpms and all(40 <= b <= 300 for b in bpms[:200])


class TestEnergyTags:
    def test_written_tags_read_back_after_reopen(self, db_copy, library, ids):
        with library.transaction():
            assert library.set_energy_tags({ids[0]: 8, ids[1]: 3}) == 2
        library.close()
        with RekordboxLibrary.open(db_copy) as reopened:
            tags = reopened.energy_tags()
        assert tags[ids[0]] == 8
        assert tags[ids[1]] == 3

    def test_rewriting_same_levels_changes_nothing(self, library, ids):
        with library.transaction():
            library.set_energy_tags({ids[0]: 8})
        with library.transaction():
            assert library.set_energy_tags({ids[0]: 8}) == 0

    def test_new_level_replaces_old_one(self, library, ids):
        with library.transaction():
            library.set_energy_tags({ids[0]: 8})
        with library.transaction():
            assert library.set_energy_tags({ids[0]: 5}) == 1
        assert library.energy_tags()[ids[0]] == 5

    def test_tags_are_shared_between_tracks(self, library, ids):
        with library.transaction():
            library.set_energy_tags({i: 6 for i in ids})
        names = [t.Name for t in library._db.get_my_tag().all() if t.Name == "Energy 6"]
        assert names == ["Energy 6"]

    def test_other_my_tags_are_untouched(self, library, ids):
        before = {(t.ID, t.Name) for t in library._db.get_my_tag().all()
                  if parse_energy_tag(t.Name or "") is None and t.Name not in ("Energy", "Untitled Column")}
        with library.transaction():
            library.set_energy_tags({ids[0]: 4})
        after = {(t.ID, t.Name) for t in library._db.get_my_tag().all()}
        assert before <= after

    def test_at_most_four_columns(self, library, ids):
        with library.transaction():
            library.set_energy_tags({ids[0]: 4})
        columns = [t for t in library._db.get_my_tag(ParentID="root").all() if int(t.Attribute or 0) == 1]
        assert len(columns) <= 4
        assert "Energy" in [c.Name for c in columns]
