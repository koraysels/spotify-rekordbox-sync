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
