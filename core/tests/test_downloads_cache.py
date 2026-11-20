from rbsync.cache import Cache


def test_record_and_get_download(tmp_path):
    cache = Cache(tmp_path / "c.db")
    cache.record_download("sp1", status="done", path="/x/a.mp3", playlist_name="Warmup")
    rec = cache.get_downloads(["sp1", "sp2"])
    assert set(rec) == {"sp1"}
    assert rec["sp1"].status == "done" and rec["sp1"].path == "/x/a.mp3"


def test_record_download_upserts(tmp_path):
    cache = Cache(tmp_path / "c.db")
    cache.record_download("sp1", status="failed", error="boom")
    cache.record_download("sp1", status="done", path="/x/a.mp3")
    assert cache.get_downloads(["sp1"])["sp1"].error == ""


def test_v5_cache_upgrades_without_losing_decisions(tmp_path):
    db = tmp_path / "c.db"
    cache = Cache(db)
    cache.remember_decision("keep", "c1", True)
    cache._db.execute("DROP TABLE downloads")
    cache._db.execute("PRAGMA user_version=5")
    cache._db.commit()
    cache.close()

    reopened = Cache(db)
    assert reopened.get_decision("keep") is not None
    reopened.record_download("sp1", status="done")
    assert reopened.get_downloads(["sp1"])["sp1"].status == "done"
