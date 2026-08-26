"""The rekordbox playlist tree, as rekordbox itself shows it."""

import pytest

from rbsync.rekordbox import SPOTIFY_FOLDER, RekordboxLibrary


@pytest.fixture
def library(db_copy):
    lib = RekordboxLibrary.open(db_copy)
    yield lib
    lib.close()


class TestTree:
    def test_returns_every_playlist(self, library):
        tree = library.playlist_tree()
        assert len(tree) == len(library.list_playlists())

    def test_nodes_carry_what_a_tree_needs(self, library):
        tree = library.playlist_tree()
        assert tree, "expected playlists in the fixture library"
        node = tree[0]
        assert set(node) >= {"id", "name", "parentId", "isFolder", "trackCount"}

    def test_folders_are_flagged(self, library):
        folder = library.ensure_folder(SPOTIFY_FOLDER)
        library.commit()
        node = next(n for n in library.playlist_tree() if n["id"] == folder.id)
        assert node["isFolder"] is True

    def test_playlists_are_not_folders(self, library):
        folder = library.ensure_folder(SPOTIFY_FOLDER)
        playlist = library.ensure_playlist("Tree Leaf", folder.id)
        library.commit()
        node = next(n for n in library.playlist_tree() if n["id"] == playlist.id)
        assert node["isFolder"] is False
        assert node["parentId"] == folder.id

    def test_track_counts_match_the_playlist_contents(self, library):
        tracks = [t.id for t in library.load_tracks() if t.title][:3]
        folder = library.ensure_folder(SPOTIFY_FOLDER)
        playlist = library.ensure_playlist("Tree Counted", folder.id)
        library.add_tracks(playlist.id, tracks)
        library.commit()
        node = next(n for n in library.playlist_tree() if n["id"] == playlist.id)
        assert node["trackCount"] == len(tracks)
