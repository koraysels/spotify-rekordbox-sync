"""Backups, the baseline, and restoring.

The rolling backups protect against the last write. They do not protect the
state the library was in before this tool ever touched it, because after ten
syncs every one of them is post-rbsync. That baseline is kept separately and
never pruned.
"""

import pytest

from rbsync.rekordbox import (
    BACKUP_PREFIX,
    ORIGINAL_PREFIX,
    BackupFailed,
    RekordboxRunning,
    ensure_baseline_backup,
    ensure_safe_to_write,
    list_backups,
    prune_backups,
    restore_backup,
)


@pytest.fixture
def library(tmp_path, monkeypatch):
    db = tmp_path / "master.db"
    db.write_bytes(b"original-library" * 64)
    monkeypatch.setattr("rbsync.rekordbox.is_rekordbox_running", lambda: False)
    return db, tmp_path / "backups"


class TestBaseline:
    def test_baseline_is_created_on_first_write(self, library):
        db, backups = library
        ensure_safe_to_write(db, backups)
        originals = list(backups.glob(f"{ORIGINAL_PREFIX}*.db"))
        assert len(originals) == 1

    def test_baseline_is_created_only_once(self, library):
        db, backups = library
        ensure_safe_to_write(db, backups)
        db.write_bytes(b"changed")
        ensure_safe_to_write(db, backups)
        assert len(list(backups.glob(f"{ORIGINAL_PREFIX}*.db"))) == 1

    def test_baseline_holds_the_pre_change_bytes(self, library):
        db, backups = library
        before = db.read_bytes()
        ensure_safe_to_write(db, backups)
        db.write_bytes(b"changed by a sync")
        ensure_safe_to_write(db, backups)
        original = next(iter(backups.glob(f"{ORIGINAL_PREFIX}*.db")))
        assert original.read_bytes() == before

    def test_pruning_never_removes_the_baseline(self, library):
        db, backups = library
        ensure_baseline_backup(db, backups)
        backups.mkdir(parents=True, exist_ok=True)
        for i in range(15):
            (backups / f"{BACKUP_PREFIX}2026-01-{i + 1:02d}T00-00-00.db").write_bytes(b"x")
        prune_backups(backups, keep=3)
        assert len(list(backups.glob(f"{ORIGINAL_PREFIX}*.db"))) == 1
        assert len(list(backups.glob(f"{BACKUP_PREFIX}*.db"))) == 3


class TestListing:
    def test_lists_newest_first(self, library):
        db, backups = library
        backups.mkdir(parents=True)
        for day in (1, 3, 2):
            (backups / f"{BACKUP_PREFIX}2026-01-0{day}T00-00-00.db").write_bytes(b"xx")
        names = [entry["name"] for entry in list_backups(backups)]
        assert names[0].endswith("03T00-00-00.db")

    def test_marks_the_baseline(self, library):
        db, backups = library
        ensure_baseline_backup(db, backups)
        entries = list_backups(backups)
        assert any(entry["isOriginal"] for entry in entries)

    def test_reports_size_and_path(self, library):
        db, backups = library
        ensure_baseline_backup(db, backups)
        entry = list_backups(backups)[0]
        assert entry["size"] == db.stat().st_size
        assert entry["path"].endswith(".db")

    def test_missing_directory_is_empty(self, tmp_path):
        assert list_backups(tmp_path / "nope") == []


class TestRestore:
    def test_restores_the_bytes(self, library):
        db, backups = library
        original = db.read_bytes()
        ensure_safe_to_write(db, backups)
        backup = next(iter(backups.glob("*.db")))
        db.write_bytes(b"broken")
        restore_backup(backup, db, backups)
        assert db.read_bytes() == original

    def test_keeps_a_copy_of_what_it_replaced(self, library):
        db, backups = library
        ensure_safe_to_write(db, backups)
        backup = next(iter(backups.glob(f"{ORIGINAL_PREFIX}*.db")))
        db.write_bytes(b"state-before-restore")
        restore_backup(backup, db, backups)
        # Restoring is itself a change, so it must be undoable too.
        assert any(
            path.read_bytes() == b"state-before-restore" for path in backups.glob("*.db")
        )

    def test_refuses_while_rekordbox_is_running(self, library, monkeypatch):
        db, backups = library
        ensure_safe_to_write(db, backups)
        backup = next(iter(backups.glob("*.db")))
        monkeypatch.setattr("rbsync.rekordbox.is_rekordbox_running", lambda: True)
        with pytest.raises(RekordboxRunning):
            restore_backup(backup, db, backups)

    def test_refuses_a_missing_backup(self, library):
        db, backups = library
        with pytest.raises(BackupFailed):
            restore_backup(backups / "nothing.db", db, backups)

    def test_leaves_the_database_untouched_when_it_refuses(self, library, monkeypatch):
        db, backups = library
        ensure_safe_to_write(db, backups)
        backup = next(iter(backups.glob("*.db")))
        db.write_bytes(b"current")
        monkeypatch.setattr("rbsync.rekordbox.is_rekordbox_running", lambda: True)
        with pytest.raises(RekordboxRunning):
            restore_backup(backup, db, backups)
        assert db.read_bytes() == b"current"


class TestUniqueNames:
    def test_two_backups_in_the_same_second_do_not_collide(self, library):
        from rbsync.rekordbox import backup_database

        db, backups = library
        first = backup_database(db, backups)
        db.write_bytes(b"second state")
        second = backup_database(db, backups)
        assert first != second
        assert first.exists() and second.exists()

    def test_the_earlier_backup_keeps_its_contents(self, library):
        from rbsync.rekordbox import backup_database

        db, backups = library
        original = db.read_bytes()
        first = backup_database(db, backups)
        db.write_bytes(b"second state")
        backup_database(db, backups)
        assert first.read_bytes() == original


class TestServiceGuards:
    """Restore replaces master.db, so the source must be one of our backups."""

    @pytest.fixture
    def service(self, tmp_path, monkeypatch):
        from rbsync.app import AppService
        from rbsync.cache import Cache

        monkeypatch.setenv("RBSYNC_HOME", str(tmp_path / "home"))
        db = tmp_path / "master.db"
        db.write_bytes(b"live library")
        monkeypatch.setattr("rbsync.rekordbox.is_rekordbox_running", lambda: False)
        svc = AppService(db_path=db, cache=Cache(tmp_path / "cache.db"))
        yield svc
        svc.close()

    def test_refuses_a_path_outside_the_backup_folder(self, service, tmp_path):
        stranger = tmp_path / "elsewhere.db"
        stranger.write_bytes(b"not ours")
        with pytest.raises(ValueError):
            service.restore_backup(str(stranger))

    def test_refuses_a_traversal_path(self, service):
        with pytest.raises(ValueError):
            service.restore_backup("../../etc/hosts")

    def test_accepts_a_backup_it_made(self, service):
        created = service.create_backup()
        service.restore_backup(created["path"])
        assert service.db_path.read_bytes() == b"live library"

    def test_creating_a_backup_lists_it(self, service):
        service.create_backup()
        assert len(service.list_backups()) >= 1


class TestWriteAheadLog:
    """SQLite keeps recent commits in a -wal sidecar.

    rekordbox runs its database in WAL mode, so master.db on its own can be
    hours out of date: the real state is master.db plus master.db-wal. Copying
    only the main file produces a backup that silently misses everything since
    the last checkpoint, and restoring only the main file leaves the WAL behind
    so the changes replay straight back.
    """

    @pytest.fixture
    def walled(self, tmp_path, monkeypatch):
        db = tmp_path / "master.db"
        db.write_bytes(b"main-file")
        (tmp_path / "master.db-wal").write_bytes(b"pending-commits")
        (tmp_path / "master.db-shm").write_bytes(b"shared-memory")
        monkeypatch.setattr("rbsync.rekordbox.is_rekordbox_running", lambda: False)
        return db, tmp_path / "backups"

    def test_backup_captures_the_wal(self, walled):
        from rbsync.rekordbox import backup_database

        db, backups = walled
        target = backup_database(db, backups)
        assert (backups / f"{target.name}-wal").read_bytes() == b"pending-commits"

    def test_backup_captures_the_shm(self, walled):
        from rbsync.rekordbox import backup_database

        db, backups = walled
        target = backup_database(db, backups)
        assert (backups / f"{target.name}-shm").exists()

    def test_baseline_captures_the_wal(self, walled):
        db, backups = walled
        target = ensure_baseline_backup(db, backups)
        assert (backups / f"{target.name}-wal").exists()

    def test_restore_puts_the_wal_back(self, walled):
        from rbsync.rekordbox import backup_database

        db, backups = walled
        target = backup_database(db, backups)
        (db.parent / "master.db-wal").write_bytes(b"newer-commits")
        restore_backup(target, db, backups)
        assert (db.parent / "master.db-wal").read_bytes() == b"pending-commits"

    def test_restore_removes_a_wal_the_backup_did_not_have(self, tmp_path, monkeypatch):
        from rbsync.rekordbox import backup_database

        monkeypatch.setattr("rbsync.rekordbox.is_rekordbox_running", lambda: False)
        db = tmp_path / "master.db"
        db.write_bytes(b"clean")
        backups = tmp_path / "backups"
        target = backup_database(db, backups)

        # A WAL appears after the backup was taken; restoring must not leave it
        # behind, or its commits replay on top of the restored file.
        (tmp_path / "master.db-wal").write_bytes(b"commits-after-backup")
        restore_backup(target, db, backups)
        assert not (tmp_path / "master.db-wal").exists()

    def test_pruning_removes_sidecars_too(self, walled):
        from rbsync.rekordbox import backup_database

        db, backups = walled
        for _ in range(4):
            backup_database(db, backups)
        prune_backups(backups, keep=1)
        assert len(list(backups.glob(f"{BACKUP_PREFIX}*.db"))) == 1
        assert len(list(backups.glob(f"{BACKUP_PREFIX}*.db-wal"))) == 1

    def test_listing_ignores_sidecar_files(self, walled):
        from rbsync.rekordbox import backup_database

        db, backups = walled
        backup_database(db, backups)
        names = [entry["name"] for entry in list_backups(backups)]
        assert all(not name.endswith("-wal") and not name.endswith("-shm") for name in names)
