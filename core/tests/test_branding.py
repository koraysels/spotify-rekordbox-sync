import pytest

from rbsync import branding
from rbsync.app import AppService
from rbsync.cache import Cache


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
    svc = AppService(db_path=tmp_path / "none.db", cache=Cache(tmp_path / "cache.db"))
    yield svc
    svc.close()


class TestDefaultClientId:
    def test_env_var_overrides_the_baked_value(self, monkeypatch):
        monkeypatch.setenv("RBSYNC_SPOTIFY_CLIENT_ID", "from-env")
        assert branding.default_client_id() == "from-env"

    def test_whitespace_is_trimmed(self, monkeypatch):
        monkeypatch.setenv("RBSYNC_SPOTIFY_CLIENT_ID", "  padded  ")
        assert branding.default_client_id() == "padded"

    def test_absent_default_is_empty(self, monkeypatch):
        monkeypatch.delenv("RBSYNC_SPOTIFY_CLIENT_ID", raising=False)
        monkeypatch.setattr(branding, "DEFAULT_SPOTIFY_CLIENT_ID", "")
        assert branding.default_client_id() == ""


class TestServiceUsesDefault:
    def test_bundled_id_is_used_when_nothing_is_configured(self, service, monkeypatch):
        monkeypatch.setenv("RBSYNC_SPOTIFY_CLIENT_ID", "bundled")
        assert service.client_id() == "bundled"

    def test_user_setting_wins_over_bundled(self, service, monkeypatch):
        monkeypatch.setenv("RBSYNC_SPOTIFY_CLIENT_ID", "bundled")
        service.cache.set_setting("spotify_client_id", "mine")
        assert service.client_id() == "mine"

    def test_status_reports_ready_when_bundled(self, service, monkeypatch):
        monkeypatch.setenv("RBSYNC_SPOTIFY_CLIENT_ID", "bundled")
        status = service.status()
        assert status["client_id_set"] is True
        assert status["client_id_is_bundled"] is True

    def test_status_flags_user_supplied_id(self, service, monkeypatch):
        monkeypatch.setenv("RBSYNC_SPOTIFY_CLIENT_ID", "bundled")
        service.cache.set_setting("spotify_client_id", "mine")
        assert service.status()["client_id_is_bundled"] is False

    def test_status_reports_not_ready_without_any_id(self, service, monkeypatch):
        monkeypatch.delenv("RBSYNC_SPOTIFY_CLIENT_ID", raising=False)
        monkeypatch.setattr(branding, "DEFAULT_SPOTIFY_CLIENT_ID", "")
        assert service.status()["client_id_set"] is False


class TestDatabaseOverride:
    def test_env_var_selects_the_database(self, tmp_path, monkeypatch):
        from rbsync.app import AppService
        from rbsync.cache import Cache

        target = tmp_path / "elsewhere.db"
        target.write_bytes(b"")
        monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
        monkeypatch.setenv("RBSYNC_DB_PATH", str(target))
        service = AppService(cache=Cache(tmp_path / "cache.db"))
        try:
            assert service.db_path == target
        finally:
            service.close()

    def test_explicit_path_wins_over_env(self, tmp_path, monkeypatch):
        from rbsync.app import AppService
        from rbsync.cache import Cache

        monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))
        monkeypatch.setenv("RBSYNC_DB_PATH", str(tmp_path / "env.db"))
        explicit = tmp_path / "explicit.db"
        service = AppService(db_path=explicit, cache=Cache(tmp_path / "cache.db"))
        try:
            assert service.db_path == explicit
        finally:
            service.close()
