import pytest

from rbsync.rekordbox import (
    BackupFailed,
    RekordboxRunning,
    backup_database,
    ensure_safe_to_write,
    prune_backups,
)


class TestBackup:
    def test_backup_copies_all_bytes(self, tmp_path):
        source = tmp_path / "master.db"
        source.write_bytes(b"x" * 4096)
        backup = backup_database(source, tmp_path / "backups")
        assert backup.exists()
        assert backup.stat().st_size == source.stat().st_size
        assert backup.read_bytes() == source.read_bytes()

    def test_backup_filename_is_timestamped(self, tmp_path):
        source = tmp_path / "master.db"
        source.write_bytes(b"data")
        backup = backup_database(source, tmp_path / "backups")
        assert backup.name.startswith("master_")
        assert backup.suffix == ".db"

    def test_missing_source_raises(self, tmp_path):
        with pytest.raises(BackupFailed):
            backup_database(tmp_path / "nope.db", tmp_path / "backups")

    def test_short_backup_raises(self, tmp_path, monkeypatch):
        source = tmp_path / "master.db"
        source.write_bytes(b"x" * 4096)

        def truncated_copy(src, dst):
            with open(dst, "wb") as fh:
                fh.write(b"x" * 10)
            return dst

        monkeypatch.setattr("rbsync.rekordbox.shutil.copy2", truncated_copy)
        with pytest.raises(BackupFailed):
            backup_database(source, tmp_path / "backups")


class TestPruning:
    def test_keeps_only_newest_n(self, tmp_path):
        backups = tmp_path / "backups"
        backups.mkdir()
        for i in range(15):
            path = backups / f"master_2026-01-{i + 1:02d}T00-00-00.db"
            path.write_bytes(b"x")
        prune_backups(backups, keep=10)
        remaining = sorted(p.name for p in backups.glob("master_*.db"))
        assert len(remaining) == 10
        assert remaining[0] == "master_2026-01-06T00-00-00.db"

    def test_pruning_ignores_unrelated_files(self, tmp_path):
        backups = tmp_path / "backups"
        backups.mkdir()
        (backups / "notes.txt").write_text("keep me")
        for i in range(12):
            (backups / f"master_2026-01-{i + 1:02d}T00-00-00.db").write_bytes(b"x")
        prune_backups(backups, keep=10)
        assert (backups / "notes.txt").exists()

    def test_pruning_empty_dir_is_safe(self, tmp_path):
        prune_backups(tmp_path / "missing", keep=10)


class TestWriteGate:
    def test_refuses_when_rekordbox_running(self, tmp_path, monkeypatch):
        source = tmp_path / "master.db"
        source.write_bytes(b"x" * 128)
        monkeypatch.setattr("rbsync.rekordbox.is_rekordbox_running", lambda: True)
        with pytest.raises(RekordboxRunning):
            ensure_safe_to_write(source, tmp_path / "backups")

    def test_returns_backup_path_when_safe(self, tmp_path, monkeypatch):
        source = tmp_path / "master.db"
        source.write_bytes(b"x" * 128)
        monkeypatch.setattr("rbsync.rekordbox.is_rekordbox_running", lambda: False)
        backup = ensure_safe_to_write(source, tmp_path / "backups")
        assert backup.exists()
