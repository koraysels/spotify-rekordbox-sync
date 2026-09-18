import pytest

from rbsync.keys import camelot_from_pitch, to_camelot


class TestMusicalNames:
    @pytest.mark.parametrize("name, camelot", [
        ("C", "8B"), ("Am", "8A"), ("Dm", "7A"), ("F#", "2B"), ("Gb", "2B"),
        ("Ebm", "2A"), ("D#m", "2A"), ("Bbm", "3A"), ("A#m", "3A"), ("Gm", "6A"),
        ("F", "7B"), ("B", "1B"), ("C#m", "12A"), ("Dbm", "12A"),
    ])
    def test_converts_note_names(self, name, camelot):
        assert to_camelot(name) == camelot

    @pytest.mark.parametrize("name", ["A min", "a minor", "Amin", "A minor"])
    def test_spelled_out_minor(self, name):
        assert to_camelot(name) == "8A"

    @pytest.mark.parametrize("name", ["Amaj", "A maj", "A major", "A"])
    def test_spelled_out_major(self, name):
        assert to_camelot(name) == "11B"

    def test_camelot_is_returned_unchanged(self):
        assert to_camelot("8A") == "8A"
        assert to_camelot("12b") == "12B"

    def test_unknown_values_are_kept(self):
        assert to_camelot("") == ""
        assert to_camelot("whatever") == "whatever"


class TestFromSpotify:
    def test_major_and_minor(self):
        assert camelot_from_pitch(0, 1) == "8B"   # C major
        assert camelot_from_pitch(9, 0) == "8A"   # A minor
        assert camelot_from_pitch(6, 1) == "2B"   # F# major

    def test_missing_values(self):
        assert camelot_from_pitch(None, 1) == ""
        assert camelot_from_pitch(-1, 1) == ""
        assert camelot_from_pitch(3, None) == ""
