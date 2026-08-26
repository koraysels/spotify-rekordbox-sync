"""Test fixtures.

Rekordbox tests run against a *copy* of a real ``master.db``. The original is
never opened by the test suite — a test that corrupts the user's library would
be far worse than a test that does not run.
"""

import os
import shutil
from pathlib import Path

import pytest

DEFAULT_DB = Path.home() / "Library" / "Pioneer" / "rekordbox" / "master.db"


def _source_db() -> Path | None:
    override = os.environ.get("RBSYNC_TEST_DB")
    if override:
        path = Path(override)
        return path if path.exists() else None
    return DEFAULT_DB if DEFAULT_DB.exists() else None


@pytest.fixture(scope="session")
def pristine_db(tmp_path_factory) -> Path:
    source = _source_db()
    if source is None:
        pytest.skip("no rekordbox master.db available on this machine")
    target = tmp_path_factory.mktemp("pristine") / "master.db"
    shutil.copy2(source, target)
    return target


@pytest.fixture
def db_copy(pristine_db, tmp_path) -> Path:
    """A throwaway copy, fresh for every test that writes."""
    target = tmp_path / "master.db"
    shutil.copy2(pristine_db, target)
    return target


@pytest.fixture
def rekordbox_closed():
    """Skip a test that writes if rekordbox is open.

    pyrekordbox refuses to commit while rekordbox is running, and rightly so.
    A test that fails for that reason is reporting the developer's desktop, not
    the code, so it skips with a message that says which.
    """
    from rbsync.rekordbox import is_rekordbox_running

    if is_rekordbox_running():
        pytest.skip("rekordbox is running; quit it to run the write tests")
