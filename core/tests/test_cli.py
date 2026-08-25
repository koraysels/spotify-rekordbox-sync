import pytest

from rbsync.cli import build_parser, main


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("RBSYNC_HOME", str(tmp_path))


class TestParser:
    def test_status_command_parses(self):
        args = build_parser().parse_args(["status"])
        assert args.command == "status"

    def test_apply_requires_yes_flag_by_default(self):
        args = build_parser().parse_args(["apply"])
        assert args.yes is False

    def test_apply_accepts_yes_flag(self):
        args = build_parser().parse_args(["apply", "--yes"])
        assert args.yes is True

    def test_select_takes_playlist_ids(self):
        args = build_parser().parse_args(["select", "a", "b"])
        assert args.playlist_ids == ["a", "b"]

    def test_config_sets_client_id(self):
        args = build_parser().parse_args(["config", "--client-id", "abc"])
        assert args.client_id == "abc"

    def test_no_command_defaults_to_none(self):
        args = build_parser().parse_args([])
        assert args.command is None


class TestApplyGuard:
    def test_apply_without_yes_refuses(self, capsys):
        code = main(["apply"])
        out = capsys.readouterr().out
        assert code != 0
        assert "--yes" in out

    def test_apply_without_yes_does_not_touch_rekordbox(self, capsys, monkeypatch):
        def explode(*a, **k):
            raise AssertionError("apply must not reach rekordbox without --yes")

        monkeypatch.setattr("rbsync.app.AppService.apply", explode)
        main(["apply"])


class TestConfigCommand:
    def test_config_persists_client_id(self, capsys):
        assert main(["config", "--client-id", "xyz"]) == 0
        assert main(["config"]) == 0
        assert "xyz" in capsys.readouterr().out

    def test_config_persists_thresholds(self, capsys):
        main(["config", "--auto-accept", "0.95"])
        main(["config"])
        assert "0.95" in capsys.readouterr().out


class TestWantlistOptions:
    def test_format_defaults_to_none(self):
        args = build_parser().parse_args(["wantlist"])
        assert args.format is None

    def test_format_accepts_txt(self):
        args = build_parser().parse_args(["wantlist", "--format", "txt"])
        assert args.format == "txt"

    def test_out_path_parses(self):
        args = build_parser().parse_args(["wantlist", "--out", "/tmp/w.csv"])
        assert args.out == "/tmp/w.csv"
