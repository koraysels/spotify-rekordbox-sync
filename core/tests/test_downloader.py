import os
import shutil
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from rbsync import downloader
from rbsync.cache import Cache
from rbsync.downloader import (
    DownloadConfig,
    Downloader,
    TrackRequest,
    is_rate_limited,
    run_process,
    safe_folder_name,
    spotdl_command,
)
from rbsync.tools import ToolMissing

TERMINAL = {"done", "failed", "cancelled"}


def cfg(tmp_path, **kw):
    return DownloadConfig(folder=tmp_path / "music", spotdl="spotdl", ffmpeg="ffmpeg", **kw)


def track(n=1, playlist="Warmup"):
    return TrackRequest(
        spotify_id=f"sp{n}", url=f"https://open.spotify.com/track/t{n}", name=f"Title {n}",
        artists=["Artist"], album="Album", isrc="", playlist_name=playlist,
    )


def out_dir_of(args):
    return Path(args[args.index("--output") + 1]).parent


def fmt_of(args):
    return args[args.index("--format") + 1]


def writes_file(name="Artist - Title"):
    """A fake runner that drops one source file into spotDL's output dir."""
    calls = []

    def run(args, cancel):
        calls.append(args)
        (out_dir_of(args) / f"{name}.{fmt_of(args)}").write_bytes(b"audio")
        return 0, "Downloaded"

    run.calls = calls
    return run


class Encoder:
    def __init__(self):
        self.kbps = []

    def __call__(self, ffmpeg, source, target, kbps, cancel=None):
        self.kbps.append(kbps)
        shutil.copyfile(source, target)


def wait_until(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached in time")


@pytest.fixture
def env(tmp_path):
    made = []
    cache = Cache(tmp_path / "c.db")
    events = []

    def make(run, config=None, encode=None):
        d = Downloader(
            cache,
            config or (lambda: cfg(tmp_path)),
            lambda method, params: events.append((method, dict(params))),
            run=run,
            measure=lambda ffmpeg, path: 160.0,
            encode=encode or Encoder(),
        )
        made.append(d)
        return d

    make.cache = cache
    make.events = events
    make.folder = tmp_path / "music"
    yield make
    for d in made:
        d.shutdown()
    cache.close()


def job_states(d):
    return {j["spotifyId"]: j["state"] for j in d.status()["jobs"]}


def wait_all_terminal(d):
    wait_until(lambda: d.status()["jobs"] and all(j["state"] in TERMINAL for j in d.status()["jobs"]))


@pytest.mark.parametrize("name,expected", [
    ("Techno / Warmup: 2026?", "Techno _ Warmup_ 2026_"),
    ("CON", "_CON"), ("trailing...", "trailing"), ("", "Playlist"), ("🔥 Sets", "🔥 Sets")])
def test_safe_folder_name(name, expected):
    assert safe_folder_name(name) == expected


def test_safe_folder_name_is_cut_to_120():
    assert len(safe_folder_name("a" * 300)) == 120


def test_spotdl_command_has_opus_no_conversion_and_secret_only_when_set(tmp_path):
    cmd = spotdl_command(cfg(tmp_path), "https://open.spotify.com/track/x", tmp_path)
    assert cmd[1:3] == ["download", "https://open.spotify.com/track/x"]
    assert ["--format", "opus"] == cmd[cmd.index("--format"):cmd.index("--format") + 2]
    assert "--bitrate" in cmd and cmd[cmd.index("--bitrate") + 1] == "disable"
    assert "--client-secret" not in cmd
    assert "--client-secret" in spotdl_command(cfg(tmp_path, client_id="i", client_secret="s"), "u", tmp_path)


def test_is_rate_limited():
    assert is_rate_limited("HTTP Error 429: Too Many Requests")
    assert is_rate_limited("Your application has reached a Rate Limit")
    assert not is_rate_limited("LookupError: No results found")


def test_run_process_returns_combined_output():
    rc, out = run_process(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"],
        threading.Event(),
    )
    assert rc == 3 and "out" in out and "err" in out


def test_run_process_kills_on_cancel():
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    rc, _ = run_process([sys.executable, "-c", "import time; time.sleep(30)"], cancel)
    assert rc != 0 and time.monotonic() - started < 5


def test_run_process_cancel_kills_grandchildren(tmp_path):
    # spotDL's onefile binary is a bootloader plus a child; both must go.
    pid_file = tmp_path / "pid"
    script = (
        "import subprocess, sys, time\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"open({str(pid_file) + '.tmp'!r}, 'w').write(str(p.pid))\n"
        f"import os; os.replace({str(pid_file) + '.tmp'!r}, {str(pid_file)!r})\n"
        "time.sleep(30)\n"
    )
    cancel = threading.Event()
    threading.Thread(target=lambda: (wait_until(pid_file.exists), cancel.set()), daemon=True).start()
    started = time.monotonic()
    run_process([sys.executable, "-c", script], cancel)
    assert time.monotonic() - started < 5
    grandchild = int(pid_file.read_text())

    def gone():
        try:
            return psutil.Process(grandchild).status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return True

    wait_until(gone)


def test_one_track_end_to_end(env):
    encoder = Encoder()
    d = env(writes_file(), encode=encoder)
    [job] = d.enqueue([track()])
    assert job["state"] == "queued" and job["spotifyId"] == "sp1"
    wait_all_terminal(d)

    target = env.folder / "Warmup" / "Artist - Title.mp3"
    assert target.read_bytes() == b"audio"
    assert encoder.kbps == [224]
    rec = env.cache.get_downloads(["sp1"])["sp1"]
    assert rec.status == "done" and rec.path == str(target) and rec.playlist_name == "Warmup"
    states = [p["state"] for m, p in env.events if m == "download.progress" and p["jobId"] == job["jobId"]]
    assert states == ["queued", "downloading", "converting", "done"]
    assert [p for m, p in env.events if m == "download.progress"][-1]["path"] == str(target)
    assert not (env.folder / "rbsync-tmp").exists()
    done = [p for m, p in env.events if m == "download.progress"][-1]
    assert done["message"] == "mp3 224 kbps from opus 160 kbps"


def test_enqueue_skips_queued_and_done(env, tmp_path):
    gate = threading.Event()
    inner = writes_file()

    def run(args, cancel):
        gate.wait(5)
        return inner(args, cancel)

    existing = tmp_path / "old.mp3"
    existing.write_bytes(b"x")
    env.cache.record_download("sp2", status="done", path=str(existing), playlist_name="Other")
    d = env(run)
    res = d.enqueue([track(1), track(1), track(2)])
    assert res[0]["state"] == "queued" and res[2]["state"] == "skipped"
    # A duplicate of an active job answers with that job, not a new "skipped" one.
    assert res[1]["jobId"] == res[0]["jobId"] and res[1]["state"] in {"queued", "downloading"}
    assert res[2]["path"] == str(existing)
    assert len(d.status()["jobs"]) == 1
    again = d.enqueue([track(1)])[0]
    assert again["jobId"] == res[0]["jobId"] and again["state"] in {"queued", "downloading"}
    gate.set()
    wait_all_terminal(d)
    assert len(inner.calls) == 1
    sp1_ids = {p["jobId"] for m, p in env.events if m == "download.progress" and p["spotifyId"] == "sp1"}
    assert sp1_ids == {res[0]["jobId"]}
    assert [p["state"] for m, p in env.events if p.get("spotifyId") == "sp2"] == ["skipped"]


def test_finished_job_can_be_enqueued_again_right_away(env, tmp_path):
    d = env(writes_file())
    [first] = d.enqueue([track()])
    wait_all_terminal(d)
    (env.folder / "Warmup" / "Artist - Title.mp3").unlink()
    [second] = d.enqueue([track()])
    assert second["state"] == "queued" and second["jobId"] != first["jobId"]


def test_done_record_with_deleted_file_is_downloaded_again(env, tmp_path):
    env.cache.record_download("sp1", status="done", path=str(tmp_path / "gone.mp3"))
    d = env(writes_file())
    assert d.enqueue([track(1)])[0]["state"] == "queued"
    wait_all_terminal(d)
    assert job_states(d) == {"sp1": "done"}


def test_existing_target_file_is_kept(env):
    target = env.folder / "Warmup" / "Artist - Title.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    d = env(writes_file())
    d.enqueue([track()])
    wait_all_terminal(d)
    assert target.read_bytes() == b"old"
    assert env.cache.get_downloads(["sp1"])["sp1"].path == str(target)
    assert [p.name for p in target.parent.iterdir()] == [target.name]


def test_m4a_fallback_when_opus_fails(env):
    formats = []

    def run(args, cancel):
        formats.append(fmt_of(args))
        if fmt_of(args) == "opus":
            return 1, "No opus stream available"
        (out_dir_of(args) / "Artist - Title.m4a").write_bytes(b"audio")
        return 0, ""

    d = env(run)
    d.enqueue([track()])
    wait_all_terminal(d)
    assert formats == ["opus", "m4a"]
    assert job_states(d) == {"sp1": "done"}
    assert (env.folder / "Warmup" / "Artist - Title.mp3").exists()


def test_m4a_fallback_when_opus_exits_zero_without_a_file(env):
    formats = []

    def run(args, cancel):
        formats.append(fmt_of(args))
        if fmt_of(args) == "opus":
            return 0, "LookupError: No results found for song"
        (out_dir_of(args) / "Artist - Title.m4a").write_bytes(b"audio")
        return 0, ""

    d = env(run)
    d.enqueue([track()])
    wait_all_terminal(d)
    assert formats == ["opus", "m4a"]
    assert job_states(d) == {"sp1": "done"}


def test_exit_zero_without_any_file_fails_with_explanation_and_last_line(env):
    def run(args, cancel):
        return 0, "LookupError: No results found for song\n"

    d = env(run)
    d.enqueue([track()])
    wait_all_terminal(d)
    [job] = d.status()["jobs"]
    assert job["state"] == "failed" and job["message"] == "spotDL produced no audio file: LookupError: No results found for song"


def test_failure_continues_queue(env):
    good = writes_file()

    def run(args, cancel):
        if "t1" in args[2]:
            return 1, "searching...\nLookupError: No results found\n\n"
        return good(args, cancel)

    d = env(run)
    d.enqueue([track(1), track(2)])
    wait_all_terminal(d)
    jobs = {j["spotifyId"]: j for j in d.status()["jobs"]}
    assert jobs["sp1"]["state"] == "failed"
    assert jobs["sp1"]["message"] == "spotDL produced no audio file: LookupError: No results found"
    assert jobs["sp2"]["state"] == "done"
    rec = env.cache.get_downloads(["sp1"])["sp1"]
    assert rec.status == "failed" and rec.error == "spotDL produced no audio file: LookupError: No results found"


def test_rate_limit_pauses_and_requeues(env):
    good = writes_file()
    calls = []

    def run(args, cancel):
        calls.append(fmt_of(args))
        if len(calls) == 1:
            return 1, "HTTP Error 429: Too Many Requests"
        return good(args, cancel)

    d = env(run)
    d.enqueue([track()])
    wait_until(lambda: d.status()["paused"])
    st = d.status()
    assert "rate-limited" in st["reason"].lower()
    assert job_states(d) == {"sp1": "queued"}
    assert ("download.queue", {"paused": True, "reason": st["reason"]}) in env.events
    assert calls == ["opus"]

    d.resume()
    wait_all_terminal(d)
    assert job_states(d) == {"sp1": "done"}
    assert d.status()["paused"] is False
    assert ("download.queue", {"paused": False, "reason": ""}) in env.events


@pytest.mark.skipif(os.name == "nt" or getattr(os, "geteuid", lambda: 1)() == 0,
                    reason="needs POSIX permissions and a non-root user")
def test_unwritable_folder_pauses_queue(env, tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    folder = locked / "music"
    locked.chmod(0o500)
    try:
        d = env(writes_file(), config=lambda: DownloadConfig(folder=folder, spotdl="s", ffmpeg="f"))
        d.enqueue([track()])
        wait_until(lambda: d.status()["paused"])
        assert str(folder) in d.status()["reason"]
        assert job_states(d) == {"sp1": "queued"}
    finally:
        locked.chmod(0o700)


def test_missing_tool_pauses_queue(env):
    def config():
        raise ToolMissing("spotdl not found")

    d = env(writes_file(), config=config)
    d.enqueue([track()])
    wait_until(lambda: d.status()["paused"])
    assert d.status()["reason"] == "spotdl not found"
    assert job_states(d) == {"sp1": "queued"}


def test_install_resumes_a_queue_paused_for_a_missing_tool(env, tmp_path):
    installed = threading.Event()

    def config():
        if not installed.is_set():
            raise ToolMissing("spotdl not found")
        return cfg(tmp_path)

    def task():
        installed.set()
        return "/bin/spotdl"

    d = env(writes_file(), config=config)
    d.enqueue([track()])
    wait_until(lambda: d.status()["paused"])
    d.install(task)
    wait_all_terminal(d)
    assert job_states(d) == {"sp1": "done"}
    assert d.status()["paused"] is False
    assert ("download.queue", {"paused": False, "reason": ""}) in env.events


def test_install_keeps_a_rate_limit_pause(env):
    d = env(lambda args, cancel: (1, "HTTP Error 429: Too Many Requests"))
    d.enqueue([track()])
    wait_until(lambda: d.status()["paused"])
    d.install(lambda: "/bin/spotdl")
    wait_until(lambda: any(p.get("jobId") == "install" and p["state"] == "done" for _, p in env.events))
    st = d.status()
    assert st["paused"] is True and "rate-limited" in st["reason"].lower()
    assert job_states(d) == {"sp1": "queued"}


def test_worker_survives_a_failing_cache_write(env, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(env.cache, "record_download", broken)
    d = env(writes_file())
    d.enqueue([track(1), track(2)])
    wait_all_terminal(d)
    jobs = d.status()["jobs"]
    assert [j["state"] for j in jobs] == ["failed", "failed"]
    assert all(j["message"] == "disk I/O error" for j in jobs)
    assert any(t.name == "rbsync-downloader" and t.is_alive() for t in threading.enumerate())


def test_status_keeps_at_most_the_last_finished_jobs(env, monkeypatch):
    monkeypatch.setattr(downloader, "MAX_FINISHED", 2)
    d = env(lambda args, cancel: (1, "boom"))
    d.enqueue([track(n) for n in range(1, 5)])
    wait_until(lambda: len(env.cache.get_downloads(["sp4"])) == 1
               and [j["spotifyId"] for j in d.status()["jobs"]] == ["sp3", "sp4"])


def blocking_runner():
    started = threading.Event()
    seen_cancel = threading.Event()

    def run(args, cancel):
        (out_dir_of(args) / "Artist - Title.opus.part").write_bytes(b"half")
        started.set()
        cancel.wait(5)
        if cancel.is_set():
            seen_cancel.set()
        return -9, ""

    run.started = started
    run.seen_cancel = seen_cancel
    return run


def test_cancel_leaves_no_partial_file(env):
    run = blocking_runner()
    d = env(run)
    [job] = d.enqueue([track()])
    assert run.started.wait(5)
    assert d.cancel(job["jobId"]) == 1
    wait_all_terminal(d)
    assert job_states(d) == {"sp1": "cancelled"}
    assert list((env.folder / "Warmup").iterdir()) == []
    assert not (env.folder / "rbsync-tmp").exists()
    assert "sp1" not in env.cache.get_downloads(["sp1"])


def test_cancel_all_drops_queued_jobs(env):
    run = blocking_runner()
    d = env(run)
    d.enqueue([track(1), track(2)])
    assert run.started.wait(5)
    assert d.cancel() == 2
    wait_all_terminal(d)
    assert job_states(d) == {"sp1": "cancelled", "sp2": "cancelled"}


def test_temp_dir_wiped_on_start_under_both_names(env):
    stale = [env.folder / name / "old" / "x.part" for name in (".rbsync-tmp", "rbsync-tmp")]
    for f in stale:
        f.parent.mkdir(parents=True)
        f.write_bytes(b"x")
    d = env(writes_file())
    d.enqueue([track()])
    wait_all_terminal(d)
    assert not any(f.parent.exists() for f in stale)
    assert not (env.folder / ".rbsync-tmp").exists() and not (env.folder / "rbsync-tmp").exists()


def test_secret_never_in_notifications(env, tmp_path):
    def run(args, cancel):
        return 1, "running spotdl --client-secret s3cret\nerror for --client-secret s3cret"

    d = env(run, config=lambda: cfg(tmp_path, client_id="id", client_secret="s3cret"))
    d.enqueue([track()])
    wait_all_terminal(d)
    assert job_states(d) == {"sp1": "failed"}
    assert env.events and not any("s3cret" in str(p) for _, p in env.events)
    assert "s3cret" not in str(d.status())
    assert "s3cret" not in env.cache.get_downloads(["sp1"])["sp1"].error


def test_shutdown_cancels_running_job(env):
    run = blocking_runner()
    d = env(run)
    d.enqueue([track()])
    assert run.started.wait(5)
    started = time.monotonic()
    d.shutdown()
    assert time.monotonic() - started < 5
    assert run.seen_cancel.is_set()
    assert not any(t.name == "rbsync-downloader" and t.is_alive() for t in threading.enumerate())


def test_install_runs_on_worker_and_reports(env):
    d = env(writes_file())
    assert d.install(lambda: "/bin/spotdl") == {"jobId": "install"}
    wait_until(lambda: any(p.get("jobId") == "install" and p["state"] == "done" for _, p in env.events))
    states = [p["state"] for m, p in env.events if m == "download.progress" and p["jobId"] == "install"]
    assert states == ["downloading", "done"]


def test_install_failure_is_reported(env):
    def boom():
        raise RuntimeError("checksum mismatch")

    d = env(writes_file())
    d.install(boom)
    wait_until(lambda: any(p.get("jobId") == "install" and p["state"] == "failed" for _, p in env.events))
    [failed] = [p for _, p in env.events if p.get("jobId") == "install" and p["state"] == "failed"]
    assert failed["message"] == "checksum mismatch"
