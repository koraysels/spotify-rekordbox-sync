import pytest

from rbsync.rekordbox import SPOTIFY_FOLDER, RekordboxLibrary


@pytest.fixture
def library(db_copy, rekordbox_closed):
    lib = RekordboxLibrary.open(db_copy)
    yield lib
    lib.close()


@pytest.fixture
def content_ids(library):
    tracks = [t for t in library.load_tracks() if t.title][:3]
    assert len(tracks) == 3, "fixture library needs at least three titled tracks"
    return [t.id for t in tracks]


class TestFolders:
    def test_creates_spotify_folder(self, library):
        folder = library.ensure_folder(SPOTIFY_FOLDER)
        library.commit()
        assert folder.id
        assert folder.name == SPOTIFY_FOLDER

    def test_ensure_folder_is_idempotent(self, library):
        first = library.ensure_folder(SPOTIFY_FOLDER)
        library.commit()
        second = library.ensure_folder(SPOTIFY_FOLDER)
        library.commit()
        assert first.id == second.id


class TestPlaylists:
    def test_creates_playlist_under_folder(self, library):
        folder = library.ensure_folder(SPOTIFY_FOLDER)
        playlist = library.ensure_playlist("Test Playlist", folder.id)
        library.commit()
        assert playlist.parent_id == folder.id

    def test_ensure_playlist_is_idempotent(self, library):
        folder = library.ensure_folder(SPOTIFY_FOLDER)
        first = library.ensure_playlist("Test Playlist", folder.id)
        library.commit()
        second = library.ensure_playlist("Test Playlist", folder.id)
        library.commit()
        assert first.id == second.id

    def test_playlist_is_visible_after_reopen(self, db_copy, rekordbox_closed):
        with RekordboxLibrary.open(db_copy) as lib:
            folder = lib.ensure_folder(SPOTIFY_FOLDER)
            lib.ensure_playlist("Persisted", folder.id)
            lib.commit()

        with RekordboxLibrary.open(db_copy) as lib:
            assert lib.find_playlist("Persisted") is not None


class TestTracks:
    def test_adds_tracks_in_order(self, library, content_ids):
        folder = library.ensure_folder(SPOTIFY_FOLDER)
        playlist = library.ensure_playlist("Ordered", folder.id)
        library.add_tracks(playlist.id, content_ids)
        library.commit()
        assert library.playlist_content_ids(playlist.id) == content_ids

    def test_does_not_duplicate_existing_tracks(self, library, content_ids):
        folder = library.ensure_folder(SPOTIFY_FOLDER)
        playlist = library.ensure_playlist("NoDupes", folder.id)
        library.add_tracks(playlist.id, content_ids)
        library.commit()
        added = library.add_tracks(playlist.id, content_ids)
        library.commit()
        assert added == 0
        assert library.playlist_content_ids(playlist.id) == content_ids

    def test_removes_only_named_tracks(self, library, content_ids):
        folder = library.ensure_folder(SPOTIFY_FOLDER)
        playlist = library.ensure_playlist("Removals", folder.id)
        library.add_tracks(playlist.id, content_ids)
        library.commit()

        library.remove_tracks(playlist.id, [content_ids[1]])
        library.commit()
        remaining = library.playlist_content_ids(playlist.id)
        assert content_ids[1] not in remaining
        assert content_ids[0] in remaining
        assert content_ids[2] in remaining

    def test_new_playlist_starts_empty(self, library):
        folder = library.ensure_folder(SPOTIFY_FOLDER)
        playlist = library.ensure_playlist("Empty", folder.id)
        library.commit()
        assert library.playlist_content_ids(playlist.id) == []


class TestTransaction:
    def test_rollback_discards_playlist(self, db_copy, rekordbox_closed):
        with RekordboxLibrary.open(db_copy) as lib:
            folder = lib.ensure_folder(SPOTIFY_FOLDER)
            lib.ensure_playlist("Doomed", folder.id)
            lib.rollback()

        with RekordboxLibrary.open(db_copy) as lib:
            assert lib.find_playlist("Doomed") is None

    def test_failure_inside_transaction_leaves_db_untouched(self, db_copy, rekordbox_closed):
        with pytest.raises(RuntimeError):
            with RekordboxLibrary.open(db_copy) as lib:
                with lib.transaction():
                    folder = lib.ensure_folder(SPOTIFY_FOLDER)
                    lib.ensure_playlist("Aborted", folder.id)
                    raise RuntimeError("boom")

        with RekordboxLibrary.open(db_copy) as lib:
            assert lib.find_playlist("Aborted") is None
