"""A background queue that downloads missing Spotify tracks with spotDL.

The RPC loop handles one call at a time, so jobs run on a single worker thread
and report through ``download.progress`` / ``download.queue`` notifications.
spotDL writes into a per-job temp dir under ``<folder>/.rbsync-tmp``; only a
finished, re-encoded mp3 is moved into the playlist folder. Never touches
rekordbox's master.db.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import psutil

from .cache import Cache
from .tools import ToolMissing
from .transcode import encode_mp3_lowq, measure_audio_kbps, mp3_bitrate_for

TMP_DIR = ".rbsync-tmp"
INSTALL_JOB = "install"
RATE_LIMITED = "Rate-limited by Spotify/YouTube"
MAX_FINISHED = 200  # finished jobs kept for status(); active ones are always kept

_UNSAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_RATE_LIMIT_RE = re.compile(r"rate limit|429|too many requests", re.IGNORECASE)
_AUDIO_EXTS = {".opus", ".m4a", ".mp3", ".ogg", ".webm", ".flac", ".wav", ".aac"}
_FINISHED = {"done", "failed", "cancelled"}
_READER_GRACE = 5.0

log = logging.getLogger(__name__)

Runner = Callable[[list[str], threading.Event], tuple[int, str]]


@dataclass(frozen=True)
class TrackRequest:
    spotify_id: str
    url: str
    name: str
    artists: list[str]
    album: str
    isrc: str
    playlist_name: str


@dataclass(frozen=True)
class DownloadConfig:
    folder: Path
    spotdl: str
    ffmpeg: str
    client_id: str = ""
    client_secret: str = ""


def safe_folder_name(name: str) -> str:
    """A playlist name usable as a folder on macOS, Windows and Linux."""
    safe = _UNSAFE_RE.sub("_", name).rstrip(". ")
    if safe.split(".")[0].upper() in _RESERVED:
        safe = "_" + safe
    safe = safe[:120].rstrip(". ")
    return safe or "Playlist"


def spotdl_command(cfg: DownloadConfig, url: str, out_dir: Path, fmt: str = "opus") -> list[str]:
    cmd = [
        cfg.spotdl, "download", url,
        "--format", fmt, "--bitrate", "disable",
        "--output", str(out_dir / "{artists} - {title}.{output-ext}"),
        "--overwrite", "skip",
        "--ffmpeg", cfg.ffmpeg,
    ]
    if cfg.client_id and cfg.client_secret:
        cmd += ["--client-id", cfg.client_id, "--client-secret", cfg.client_secret]
    return cmd


def is_rate_limited(output: str) -> bool:
    return bool(_RATE_LIMIT_RE.search(output))


def run_process(args: list[str], cancel: threading.Event) -> tuple[int, str]:
    """Run ``args`` with stdout+stderr merged; kill it as soon as ``cancel`` is set."""
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    proc = subprocess.Popen(
        args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", **kwargs,
    )
    chunks: list[str] = []
    reader = threading.Thread(target=lambda: chunks.append(proc.stdout.read()), daemon=True)
    reader.start()
    while True:
        if cancel.is_set() and proc.poll() is None:
            _kill_tree(proc)
            break
        try:
            proc.wait(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            continue
    # A stray descendant can hold the pipe open; never wait on it forever.
    reader.join(timeout=_READER_GRACE)
    if not reader.is_alive():
        proc.stdout.close()  # closing under a blocked reader would block too
    return proc.returncode, "".join(chunks)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill ``proc`` and its descendants (spotDL's onefile bootloader forks a child,
    which spawns ffmpeg); a survivor would keep the pipe open and keep downloading."""
    try:
        children = psutil.Process(proc.pid).children(recursive=True)
    except psutil.Error:
        children = []
    proc.kill()
    for child in children:
        try:
            child.kill()
        except psutil.Error:
            pass
    proc.wait()


def _last_line(output: str) -> str:
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


@dataclass
class _Job:
    id: str
    track: TrackRequest
    state: str = "queued"
    message: str = ""
    path: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)

    def as_dict(self) -> dict:
        return {
            "jobId": self.id, "spotifyId": self.track.spotify_id, "name": self.track.name,
            "playlistName": self.track.playlist_name, "state": self.state,
            "message": self.message, "path": self.path,
        }

    def summary(self) -> dict:
        return {"jobId": self.id, "spotifyId": self.track.spotify_id, "state": self.state, "path": self.path}


class _Pause(Exception):
    """Stop the queue; the job goes back to the head as ``queued``."""

    def __init__(self, reason: str, *, tool: bool = False) -> None:
        super().__init__(reason)
        self.tool = tool  # a missing tool, which a successful install() fixes


class _Cancelled(Exception):
    pass


class _Failed(Exception):
    pass


class Downloader:
    def __init__(
        self,
        cache: Cache,
        config: Callable[[], DownloadConfig],
        notify: Callable[[str, dict], None],
        run: Runner = run_process,
        measure=measure_audio_kbps,
        encode=encode_mp3_lowq,
    ) -> None:
        self._cache = cache
        self._config = config
        self._notify = notify
        self._run = run
        self._measure = measure
        self._encode = encode
        # Every state change and its notification happen together under this lock,
        # so status() never runs ahead of the notifications.
        self._cond = threading.Condition()
        self._queue: deque[_Job] = deque()
        self._installs: deque[Callable[[], str]] = deque()
        self._jobs: list[_Job] = []
        self._current: _Job | None = None
        self._paused = False
        self._paused_for_tool = False
        self._reason = ""
        self._secret = ""
        self._stop = False
        self._wiped = False
        self._thread: threading.Thread | None = None

    # --- public API (called from the RPC thread) ----------------------------

    def enqueue(self, tracks: list[TrackRequest]) -> list[dict]:
        results: list[dict] = []
        with self._cond:
            done = self._cache.get_downloads([t.spotify_id for t in tracks])
            active = {j.track.spotify_id: j for j in self._queue}
            if self._current is not None:
                active[self._current.track.spotify_id] = self._current
            for t in tracks:
                existing = active.get(t.spotify_id)
                if existing is not None:
                    # Same track already on its way: answer with that job, no new row.
                    results.append(existing.summary())
                    continue
                job = _Job(uuid.uuid4().hex, t)
                rec = done.get(t.spotify_id)
                if rec and rec.status == "done" and rec.path and Path(rec.path).exists():
                    job.state, job.message, job.path = "skipped", "Already downloaded", rec.path
                else:
                    active[t.spotify_id] = job
                    self._queue.append(job)
                    self._jobs.append(job)
                self._progress(job)
                results.append(job.summary())
            if self._queue:
                self._start_locked()
            self._cond.notify_all()
        return results

    def install(self, task: Callable[[], str]) -> dict:
        with self._cond:
            self._installs.append(task)
            self._start_locked()
            self._cond.notify_all()
        return {"jobId": INSTALL_JOB}

    def cancel(self, job_id: str | None = None) -> int:
        count = 0
        with self._cond:
            for job in list(self._queue):
                if job_id is None or job.id == job_id:
                    self._queue.remove(job)
                    job.state, job.message = "cancelled", ""
                    self._progress(job)
                    count += 1
            cur = self._current
            if cur is not None and (job_id is None or cur.id == job_id) and not cur.cancel.is_set():
                cur.cancel.set()
                count += 1
            self._prune_locked()
        return count

    def resume(self) -> None:
        with self._cond:
            self._resume_locked()

    def status(self) -> dict:
        with self._cond:
            return {
                "paused": self._paused,
                "reason": self._reason,
                "jobs": [j.as_dict() for j in self._jobs],
            }

    def shutdown(self) -> None:
        with self._cond:
            self._stop = True
            if self._current is not None:
                self._current.cancel.set()
            self._cond.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=5)

    # --- worker --------------------------------------------------------------

    def _start_locked(self) -> None:
        if self._thread is None and not self._stop:
            self._thread = threading.Thread(target=self._loop, name="rbsync-downloader", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while True:
            with self._cond:
                while not self._stop and not self._installs and (self._paused or not self._queue):
                    self._cond.wait()
                if self._stop:
                    return
                if self._installs:
                    task, job = self._installs.popleft(), None
                else:
                    task, job = None, self._queue.popleft()
                    self._current = job
            if job is None:
                self._run_install(task)
                continue
            try:
                self._run_job(job)
            except Exception as e:  # noqa: BLE001 - the worker must outlive any one job
                log.exception("download job %s crashed", job.id)
                self._crashed(job, e)

    def _run_install(self, task: Callable[[], str]) -> None:
        self._emit_install("downloading", "")
        try:
            result = task()
        except Exception as e:  # noqa: BLE001 - any install error is reported, not raised
            self._emit_install("failed", str(e) or type(e).__name__)
            return
        self._emit_install("done", result or "")
        with self._cond:
            if self._paused and self._paused_for_tool:
                self._resume_locked()

    def _emit_install(self, state: str, message: str) -> None:
        self._emit("download.progress", {
            "jobId": INSTALL_JOB, "spotifyId": "", "state": state,
            "message": self._scrub(message), "path": "",
        })

    def _run_job(self, job: _Job) -> None:
        # Clean up first, then publish: once a job reads as finished, its temp
        # dir is gone and the same track can be queued again.
        tmps: list[Path] = []
        try:
            outcome = self._attempt(job, tmps)
        finally:
            for tmp in tmps:
                shutil.rmtree(tmp, ignore_errors=True)
        if isinstance(outcome, _Pause):
            self._pause(job, outcome)
            return
        state, detail = outcome
        detail = self._scrub(detail)
        if state == "done":
            self._cache.record_download(
                job.track.spotify_id, status="done", path=detail, playlist_name=job.track.playlist_name,
            )
        elif state == "failed":
            self._record_failure(job, detail)
        self._finish(job, state, detail)

    def _attempt(self, job: _Job, tmps: list[Path]) -> tuple[str, str] | _Pause:
        """Download and convert one track: ``(state, path-or-error)`` or a pause."""
        try:
            try:
                cfg = self._config()
            except ToolMissing as e:
                raise _Pause(str(e), tool=True) from None
            self._secret = cfg.client_secret
            tmp, target_dir = self._prepare(cfg, job)
            tmps.append(tmp)
            self._set(job, "downloading")
            source = self._download(cfg, job, tmp)
            self._set(job, "converting")
            kbps = mp3_bitrate_for(self._measure(cfg.ffmpeg, source))
            encoded = tmp / f"{source.stem}.rbsync.mp3"
            self._encode(cfg.ffmpeg, source, encoded, kbps, cancel=job.cancel)
            if job.cancel.is_set():
                raise _Cancelled
            final = target_dir / f"{source.stem}.mp3"
            if not final.exists():
                shutil.move(str(encoded), str(final))
            return "done", str(final)
        except _Pause as e:
            return e
        except _Cancelled:
            return "cancelled", ""
        except Exception as e:  # noqa: BLE001 - one bad track must not stop the queue
            if job.cancel.is_set():  # e.g. TranscodeError("cancelled")
                return "cancelled", ""
            return "failed", str(e) or type(e).__name__

    def _prepare(self, cfg: DownloadConfig, job: _Job) -> tuple[Path, Path]:
        root = Path(cfg.folder)
        if not self._wiped:
            self._wiped = True
            shutil.rmtree(root / TMP_DIR, ignore_errors=True)
        target_dir = root / safe_folder_name(job.track.playlist_name)
        tmp = root / TMP_DIR / job.id
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            tmp.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise _Pause(f"Download folder not writable: {root}") from None
        return tmp, target_dir

    def _download(self, cfg: DownloadConfig, job: _Job, tmp: Path) -> Path:
        rc, out = self._run(spotdl_command(cfg, job.track.url, tmp, "opus"), job.cancel)
        # spotDL can exit 0 after a per-song failure, so "no file" decides the retry.
        if not job.cancel.is_set() and not self._audio(tmp) and not is_rate_limited(out):
            rc, out = self._run(spotdl_command(cfg, job.track.url, tmp, "m4a"), job.cancel)
        if job.cancel.is_set():
            raise _Cancelled
        files = self._audio(tmp)
        if not files:
            if is_rate_limited(out):
                raise _Pause(RATE_LIMITED)
            raise _Failed(_last_line(out) or (f"spotDL exited {rc}" if rc else "spotDL produced no audio file"))
        if rc != 0:
            raise _Failed(_last_line(out) or f"spotDL exited {rc}")
        if len(files) > 1:
            raise _Failed("spotDL produced more than one file")
        return files[0]

    @staticmethod
    def _audio(tmp: Path) -> list[Path]:
        return [p for p in tmp.iterdir() if p.is_file() and p.suffix.lower() in _AUDIO_EXTS]

    # --- state + notifications (callers hold no lock) ------------------------

    def _set(self, job: _Job, state: str) -> None:
        with self._cond:
            job.state, job.message = state, ""
            self._progress(job)

    def _finish(self, job: _Job, state: str, detail: str) -> None:
        with self._cond:
            if self._current is job:
                self._current = None
            job.state = state
            job.message = detail if state == "failed" else ""
            job.path = detail if state == "done" else ""
            self._progress(job)
            self._prune_locked()

    def _record_failure(self, job: _Job, message: str) -> None:
        self._cache.record_download(
            job.track.spotify_id, status="failed", playlist_name=job.track.playlist_name, error=message,
        )

    def _crashed(self, job: _Job, error: Exception) -> None:
        message = self._scrub(str(error) or type(error).__name__)
        try:
            self._record_failure(job, message)
        except Exception:  # noqa: BLE001 - best effort; the cache may be what broke
            log.exception("could not record failed download %s", job.track.spotify_id)
        self._finish(job, "failed", message)

    def _pause(self, job: _Job, pause: _Pause) -> None:
        reason = self._scrub(str(pause))
        with self._cond:
            if self._current is job:
                self._current = None
            if job.cancel.is_set():
                job.state, job.message = "cancelled", ""
                self._progress(job)
                self._prune_locked()
                return
            job.state, job.message = "queued", ""
            self._queue.appendleft(job)
            self._paused, self._reason, self._paused_for_tool = True, reason, pause.tool
            self._progress(job)
            self._emit("download.queue", {"paused": True, "reason": reason})

    def _resume_locked(self) -> None:
        self._paused, self._reason, self._paused_for_tool = False, "", False
        self._emit("download.queue", {"paused": False, "reason": ""})
        self._cond.notify_all()

    def _prune_locked(self) -> None:
        finished = [j for j in self._jobs if j.state in _FINISHED]
        if len(finished) > MAX_FINISHED:
            drop = {id(j) for j in finished[: len(finished) - MAX_FINISHED]}
            self._jobs = [j for j in self._jobs if id(j) not in drop]

    def _progress(self, job: _Job) -> None:
        self._emit("download.progress", {
            "jobId": job.id, "spotifyId": job.track.spotify_id, "state": job.state,
            "message": self._scrub(job.message), "path": job.path,
        })

    def _scrub(self, text: str) -> str:
        return text.replace(self._secret, "***") if self._secret else text

    def _emit(self, method: str, params: dict) -> None:
        try:
            self._notify(method, params)
        except Exception:  # noqa: BLE001 - a closed pipe must not kill the worker
            pass
