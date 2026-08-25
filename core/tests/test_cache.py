import pytest

from rbsync.cache import Cache


@pytest.fixture
def cache(tmp_path):
    c = Cache(tmp_path / "cache.db")
    yield c
    c.close()


class TestDecisions:
    def test_accepted_decision_round_trips(self, cache):
        cache.remember_decision("sp1", "rb1", accepted=True)
        decision = cache.get_decision("sp1")
        assert decision.content_id == "rb1"
        assert decision.accepted is True

    def test_rejection_is_remembered_as_rejection(self, cache):
        cache.remember_decision("sp1", "rb1", accepted=False)
        decision = cache.get_decision("sp1")
        assert decision is not None
        assert decision.accepted is False

    def test_unknown_track_has_no_decision(self, cache):
        assert cache.get_decision("nope") is None

    def test_decision_survives_reopen(self, tmp_path):
        path = tmp_path / "cache.db"
        first = Cache(path)
        first.remember_decision("sp1", "rb1", accepted=True)
        first.close()

        second = Cache(path)
        assert second.get_decision("sp1").content_id == "rb1"
        second.close()

    def test_latest_decision_wins(self, cache):
        cache.remember_decision("sp1", "rb1", accepted=True)
        cache.remember_decision("sp1", "rb2", accepted=True)
        assert cache.get_decision("sp1").content_id == "rb2"

    def test_forget_removes_decision(self, cache):
        cache.remember_decision("sp1", "rb1", accepted=True)
        cache.forget_decision("sp1")
        assert cache.get_decision("sp1") is None


class TestSelection:
    def test_defaults_to_empty_selection(self, cache):
        assert cache.get_selected_playlists() == []

    def test_selection_round_trips(self, cache):
        cache.set_selected_playlists(["a", "b"])
        assert sorted(cache.get_selected_playlists()) == ["a", "b"]

    def test_selection_replaces_previous(self, cache):
        cache.set_selected_playlists(["a", "b"])
        cache.set_selected_playlists(["c"])
        assert cache.get_selected_playlists() == ["c"]

    def test_selection_survives_reopen(self, tmp_path):
        path = tmp_path / "cache.db"
        first = Cache(path)
        first.set_selected_playlists(["keep"])
        first.close()
        second = Cache(path)
        assert second.get_selected_playlists() == ["keep"]
        second.close()


class TestSyncHistory:
    def test_records_and_reads_back_stats(self, cache):
        cache.record_sync("pl1", added=5, removed=1, matched=8, total=10)
        entry = cache.get_last_sync("pl1")
        assert entry.added == 5
        assert entry.removed == 1
        assert entry.matched == 8
        assert entry.total == 10
        assert entry.synced_at

    def test_no_history_returns_none(self, cache):
        assert cache.get_last_sync("never") is None

    def test_latest_sync_is_returned(self, cache):
        cache.record_sync("pl1", added=1, removed=0, matched=1, total=1)
        cache.record_sync("pl1", added=2, removed=0, matched=2, total=2)
        assert cache.get_last_sync("pl1").added == 2


class TestSettings:
    def test_settings_round_trip(self, cache):
        cache.set_setting("auto_accept", "0.9")
        assert cache.get_setting("auto_accept") == "0.9"

    def test_missing_setting_returns_default(self, cache):
        assert cache.get_setting("nope", "fallback") == "fallback"


class TestHistoryLog:
    def test_history_returns_newest_first(self, cache):
        cache.record_sync("pl1", added=1, removed=0, matched=1, total=1)
        cache.record_sync("pl1", added=2, removed=0, matched=2, total=2)
        history = cache.get_history()
        assert [entry.added for entry in history] == [2, 1]

    def test_history_can_filter_by_playlist(self, cache):
        cache.record_sync("pl1", added=1, removed=0, matched=1, total=1)
        cache.record_sync("pl2", added=5, removed=0, matched=5, total=5)
        history = cache.get_history(playlist_id="pl2")
        assert len(history) == 1
        assert history[0].playlist_id == "pl2"

    def test_history_respects_limit(self, cache):
        for i in range(10):
            cache.record_sync("pl1", added=i, removed=0, matched=i, total=i)
        assert len(cache.get_history(limit=3)) == 3

    def test_history_records_playlist_name(self, cache):
        cache.record_sync("pl1", added=1, removed=0, matched=1, total=1, playlist_name="Bangers")
        assert cache.get_history()[0].playlist_name == "Bangers"

    def test_history_records_backup_path(self, cache):
        cache.record_sync(
            "pl1", added=1, removed=0, matched=1, total=1, backup_path="/tmp/master_x.db"
        )
        assert cache.get_history()[0].backup_path == "/tmp/master_x.db"

    def test_history_is_empty_initially(self, cache):
        assert cache.get_history() == []

    def test_history_survives_reopen(self, tmp_path):
        path = tmp_path / "cache.db"
        first = Cache(path)
        first.record_sync("pl1", added=3, removed=1, matched=3, total=4)
        first.close()
        second = Cache(path)
        assert second.get_history()[0].added == 3
        second.close()


class TestMigration:
    def test_upgrades_a_version_1_database(self, tmp_path):
        import sqlite3

        path = tmp_path / "cache.db"
        legacy = sqlite3.connect(str(path))
        legacy.executescript(
            """
            CREATE TABLE decisions (
                spotify_id TEXT PRIMARY KEY,
                content_id TEXT NOT NULL,
                accepted   INTEGER NOT NULL,
                decided_at TEXT NOT NULL
            );
            CREATE TABLE selection (playlist_id TEXT PRIMARY KEY);
            CREATE TABLE sync_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id TEXT NOT NULL,
                added       INTEGER NOT NULL,
                removed     INTEGER NOT NULL,
                matched     INTEGER NOT NULL,
                total       INTEGER NOT NULL,
                synced_at   TEXT NOT NULL
            );
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        legacy.execute(
            "INSERT INTO sync_history (playlist_id, added, removed, matched, total, synced_at)"
            " VALUES ('old', 1, 0, 1, 1, '2026-01-01T00:00:00')"
        )
        legacy.execute("PRAGMA user_version=1")
        legacy.commit()
        legacy.close()

        cache = Cache(path)
        try:
            # Existing rows survive, and the new columns read as empty.
            entry = cache.get_history()[0]
            assert entry.playlist_id == "old"
            assert entry.playlist_name == ""
            assert entry.backup_path == ""
            # And the upgraded schema accepts the new fields.
            cache.record_sync("new", added=2, removed=0, matched=2, total=2,
                              playlist_name="New", backup_path="/tmp/b.db")
            assert cache.get_history()[0].playlist_name == "New"
        finally:
            cache.close()
