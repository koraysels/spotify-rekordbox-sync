"""Re-registering playlists that exist in the database but not in the XML.

rekordbox keeps a second index of the playlist tree in masterPlaylists6.xml.
A playlist row that never made it into that file — because a write was
interrupted between the database commit and the XML save — exists in the
database but is not part of the tree rekordbox reads, so it does not show up.
"""

import pytest

from rbsync.rekordbox import SPOTIFY_FOLDER, RekordboxLibrary


@pytest.fixture
def library(db_copy):
    lib = RekordboxLibrary.open(db_copy)
    yield lib
    lib.close()


class TestRepair:
    def test_reports_nothing_to_do_on_a_consistent_library(self, library):
        # Whatever the fixture library contains, running twice must be a no-op
        # the second time.
        library.register_missing_in_xml()
        assert library.register_missing_in_xml() == 0

    def test_a_playlist_created_normally_needs_no_repair(self, library):
        folder = library.ensure_folder(SPOTIFY_FOLDER)
        library.ensure_playlist("XML Consistent", folder.id)
        library.commit()
        assert library.register_missing_in_xml() == 0

    def test_repair_is_safe_without_an_xml_file(self, library, monkeypatch):
        # Some installations have no masterPlaylists6.xml at all; the repair
        # must not crash there.
        monkeypatch.setattr(library._db, "playlist_xml", None, raising=False)
        assert library.register_missing_in_xml() == 0

    def test_missing_playlists_are_detected(self, library):
        xml = getattr(library._db, "playlist_xml", None)
        if xml is None:
            pytest.skip("fixture library has no masterPlaylists6.xml")

        folder = library.ensure_folder(SPOTIFY_FOLDER)
        playlist = library.ensure_playlist("XML Orphan", folder.id)
        library.commit()

        # Simulate the interrupted write: remove it from the XML index only.
        xml.remove(playlist.id)
        xml.save()
        assert xml.get(playlist.id) is None

        assert library.register_missing_in_xml() >= 1
        assert xml.get(playlist.id) is not None
