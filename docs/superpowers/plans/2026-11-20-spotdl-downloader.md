# spotDL Downloader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An optional downloader that fetches missing Spotify tracks with spotDL, converts them to a source-matched CBR mp3 labelled `lowq` into `<folder>/<playlist>/`, plus buy/search links for missing and `lowq` tracks.

**Architecture:** All download work lives in the Python core, on one background worker thread with a FIFO queue, so the single-threaded JSON-RPC loop stays free. spotDL fetches the Opus source unconverted; rbsync measures it and encodes once with ffmpeg. The UI drives it through new `downloader.*` RPC methods and a `download.progress` notification, and adds badges, menu items, a panel and a Settings section, without changing any existing behaviour.

**Tech Stack:** Python 3.12 core (stdlib `subprocess`/`threading`, `httpx` already a dependency), pytest; React + TypeScript UI; Tauri v2 (`tauri-plugin-dialog` added); external tools spotDL 4.6.0 and ffmpeg.

**Spec:** `docs/superpowers/specs/2026-11-20-spotdl-downloader-design.md`

## Global Constraints

- Existing features stay exactly as they are (spec, "Existing features: unchanged"). The existing test files in `core/tests/` must pass **unmodified**; never edit an existing test. If one fails, stop and report.
- Feature is off by default (`downloaderEnabled` false). Nothing downloads without a button press; no "download all playlists" action.
- spotDL pinned to **4.6.0**. Assets and SHA-256:
  - `spotdl-4.6.0-darwin` (darwin/arm64) `957bb335e773ab67fc7a65574b0465ad828849944025a84cdfc9466a4336e3bb`
  - `spotdl-4.6.0-win32.exe` (win32/AMD64) `e674030c3337cd74120a3a086887ce1a5195765cfc17e1971a2807e0a398b505`
  - `spotdl-4.6.0-linux` (linux/x86_64) `99eb14032e252af30f1c6bdc7461057c324754978afe30c6583ed6b3ec3257bf`
  - URL: `https://github.com/spotDL/spotify-downloader/releases/download/v4.6.0/<asset>`
- mp3 bitrate rule: next step in `(128, 160, 192, 224, 256)` at or above `1.25 × measured source kbps`, capped at 256, floor 128. CBR, ID3v2.3, comment exactly `lowq`. Never 320.
- Default download folder `~/Downloads/rbsync`. Per-playlist subfolder. Temp work under `<folder>/.rbsync-tmp/<jobId>/`.
- The downloader client secret is never logged, never sent in a notification, never returned by `settings.get` (only `hasDownloaderSecret`).
- Downloads never touch rekordbox's `master.db`.
- Commit messages: Conventional Commits, no `Co-Authored-By`, no "Generated with" lines.
- Run core tests with `cd core && .venv/bin/python -m pytest`; UI checks with `cd ui && npm run typecheck && npm run lint`.

## Review Focus

1. Playlist names with `/`, `:`, `?`, trailing dots, emoji, or Windows-reserved names (`CON`, `NUL`) must still produce a valid folder — tested in Task 5 (`test_safe_folder_name_*`).
2. Pressing Download twice, or the same track wanted by two playlists, must not download twice — tested in Task 5 (`test_enqueue_skips_queued_and_done`).
3. Download folder on an unplugged drive or not writable: the queue pauses with a readable reason instead of failing every track — tested in Task 5 (`test_unwritable_folder_pauses_queue`).
4. Cancel or quit mid-download/encode leaves no half file in the playlist folder, and leftovers are wiped next start — tested in Task 5 (`test_cancel_leaves_no_partial_file`, `test_temp_dir_wiped_on_start`).
5. The client secret leaking through spotDL error output into notifications or logs — tested in Task 5 (`test_secret_never_in_notifications`).

---

### Task 1: `downloads` table in the cache

**Files:**
- Modify: `core/rbsync/cache.py` (bump `SCHEMA_VERSION` to 6, add table in `_create_schema`, add dataclass and two methods)
- Test: `core/tests/test_downloads_cache.py` (new)

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True, slots=True)
  class DownloadRecord:
      spotify_id: str
      status: str          # "done" | "failed"
      path: str
      playlist_name: str
      error: str
      created_at: str
  Cache.record_download(spotify_id: str, *, status: str, path: str = "", playlist_name: str = "", error: str = "") -> None   # upsert
  Cache.get_downloads(spotify_ids: list[str]) -> dict[str, DownloadRecord]
  ```

- [ ] **Step 1: Write the failing tests**

```python
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
    # build a v5 db: create Cache, set user_version=5, drop downloads table, reopen
    ...
    assert reopened.get_decision("keep") is not None
    reopened.record_download("sp1", status="done")
```

- [ ] **Step 2: Run** `cd core && .venv/bin/python -m pytest tests/test_downloads_cache.py -v` → FAIL (`record_download` missing).
- [ ] **Step 3: Implement.** Table `downloads(spotify_id TEXT PRIMARY KEY, status TEXT NOT NULL, path TEXT NOT NULL DEFAULT '', playlist_name TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)` via `CREATE TABLE IF NOT EXISTS` in `_create_schema` (the existing `_migrate` already runs it for any version < 6). All statements under `self._lock`.
- [ ] **Step 4: Run** the new file and the full suite → all PASS.
- [ ] **Step 5: Commit** `feat(core): remember downloaded tracks in the cache`

---

### Task 2: Source-matched mp3 encode

**Files:**
- Create: `core/rbsync/transcode.py`
- Test: `core/tests/test_transcode.py` (new)

**Interfaces:**
- Produces:
  ```python
  MP3_STEPS: tuple[int, ...] = (128, 160, 192, 224, 256)
  LOWQ_COMMENT = "lowq"
  class TranscodeError(RuntimeError): ...
  def mp3_bitrate_for(source_kbps: float) -> int
  def measure_audio_kbps(ffmpeg: str, path: Path) -> float
  def encode_mp3_lowq(ffmpeg: str, source: Path, target: Path, kbps: int, cancel: threading.Event | None = None) -> None
  ```

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("src,expected", [(160, 224), (130, 192), (128, 160), (200, 256), (300, 256), (90, 128), (102.4, 128)])
def test_mp3_bitrate_for(src, expected):
    assert mp3_bitrate_for(src) == expected

def test_mp3_bitrate_rejects_zero():
    with pytest.raises(ValueError):
        mp3_bitrate_for(0)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

@needs_ffmpeg
def test_measure_opus_160(tmp_path):
    src = make_opus(tmp_path, kbps=160, seconds=10, title="Song")   # ffmpeg sine → libopus, -metadata title=Song
    assert 130 <= measure_audio_kbps(shutil.which("ffmpeg"), src) <= 175

@needs_ffmpeg
def test_encode_writes_cbr_tags_and_lowq(tmp_path):
    src = make_opus(tmp_path, kbps=160, seconds=10, title="Song")
    out = tmp_path / "out.mp3"
    encode_mp3_lowq(shutil.which("ffmpeg"), src, out, 224)
    tags = probe_tags(out)                                          # ffprobe -show_entries format_tags
    assert tags["title"] == "Song" and tags["comment"] == "lowq"
    assert 215 <= measure_audio_kbps(shutil.which("ffmpeg"), out) <= 232
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_transcode.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement.**
  - `mp3_bitrate_for`: `ValueError` for `<= 0`; target `1.25 * source_kbps`; first step `>= target`, else 256.
  - `measure_audio_kbps`: only ffmpeg is guaranteed (spotDL's `--download-ffmpeg` ships no ffprobe). Run `ffmpeg -hide_banner -i <path> -map 0:a:0 -c copy -f null -`; parse the final `audio:<N>(KiB|kB)` size and the `Duration: hh:mm:ss.xx`; kbps = `N * 8 * (1.024 if KiB) / seconds`. Audio-only size, so embedded cover art does not inflate it. `TranscodeError` when either is missing.
  - `encode_mp3_lowq`: `ffmpeg -y -hide_banner -i <src> -map 0:a:0 -map 0:v? -map_metadata 0 -c:a libmp3lame -b:a <kbps>k -c:v copy -disposition:v attached_pic -id3v2_version 3 -metadata comment=lowq <target>`; run with `subprocess.Popen`, poll `cancel` every 0.2 s and kill on set (then delete `target`, raise `TranscodeError("cancelled")`); non-zero exit → delete `target`, raise with the last stderr line. On Windows pass `creationflags=subprocess.CREATE_NO_WINDOW`.
- [ ] **Step 4: Run** → PASS (ffmpeg tests skip where ffmpeg is absent; on this Mac they must run).
- [ ] **Step 5: Commit** `feat(core): encode downloads to an mp3 bitrate matched to the source`

---

### Task 3: Finding and installing spotDL and ffmpeg

**Files:**
- Create: `core/rbsync/tools.py`
- Modify: `core/rbsync/paths.py` (add `tools_dir() -> Path` = `config_dir() / "tools"`, created)
- Test: `core/tests/test_tools.py` (new)

**Interfaces:**
- Produces:
  ```python
  SPOTDL_VERSION = "4.6.0"
  SPOTDL_ASSETS: dict[tuple[str, str], tuple[str, str]]   # (sys.platform, machine) -> (asset name, sha256), values from Global Constraints
  class ToolMissing(RuntimeError): ...
  class InstallError(RuntimeError): ...
  def asset_for(system: str, machine: str) -> tuple[str, str] | None
  def known_dirs(home: Path | None = None) -> list[Path]
  def find_spotdl(setting_path: str, tools_dir: Path, env_path: str | None = None, extra_dirs: list[Path] | None = None) -> tuple[str | None, str]   # (path, source) source in "setting"|"installed"|"path"|"known"|""
  def find_ffmpeg(env_path: str | None = None, extra_dirs: list[Path] | None = None, home: Path | None = None) -> str | None
  def install_spotdl(tools_dir: Path, fetch: Callable[[str, Path], None], system: str = sys.platform, machine: str = platform.machine()) -> Path
  def download_ffmpeg(spotdl: str) -> str | None        # runs `spotdl --download-ffmpeg`, returns find_ffmpeg() after
  ```

- [ ] **Step 1: Write the failing tests**

```python
def test_asset_for_known_and_unknown():
    assert asset_for("darwin", "arm64")[0] == "spotdl-4.6.0-darwin"
    assert asset_for("win32", "AMD64")[0] == "spotdl-4.6.0-win32.exe"
    assert asset_for("darwin", "x86_64") is None

def test_install_verifies_hash_and_deletes_on_mismatch(tmp_path):
    def fetch(url, dest): dest.write_bytes(b"not spotdl")
    with pytest.raises(InstallError, match="checksum"):
        install_spotdl(tmp_path, fetch, "darwin", "arm64")
    assert list(tmp_path.iterdir()) == []

def test_install_success_is_executable(tmp_path, monkeypatch):
    payload = b"fake"
    monkeypatch.setitem(SPOTDL_ASSETS, ("darwin", "arm64"), ("spotdl-4.6.0-darwin", hashlib.sha256(payload).hexdigest()))
    path = install_spotdl(tmp_path, lambda url, dest: dest.write_bytes(payload), "darwin", "arm64")
    assert os.access(path, os.X_OK)

def test_install_without_asset_raises_with_instructions(tmp_path):
    with pytest.raises(InstallError, match="pipx install spotdl"):
        install_spotdl(tmp_path, lambda u, d: None, "darwin", "x86_64")

def test_find_spotdl_order(tmp_path):
    # setting beats installed beats PATH beats known dirs
    ...
    assert find_spotdl(str(setting_bin), tools, env_path=str(path_dir))[1] == "setting"
    assert find_spotdl("", tools, env_path=str(path_dir))[1] == "installed"

def test_find_spotdl_in_known_dir_when_path_is_minimal(tmp_path):
    brew = tmp_path / "brew"; make_exe(brew / "spotdl")
    assert find_spotdl("", tmp_path / "empty", env_path="/usr/bin", extra_dirs=[brew]) == (str(brew / "spotdl"), "known")

def test_find_ffmpeg_uses_spotdl_copy(tmp_path):
    make_exe(tmp_path / ".spotdl" / "ffmpeg")
    assert find_ffmpeg(env_path="", extra_dirs=[], home=tmp_path).endswith("ffmpeg")
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_tools.py -v` → FAIL.
- [ ] **Step 3: Implement.** Installed binary path `tools_dir / <asset name>`. `known_dirs`: `/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin`, and on Windows `%LOCALAPPDATA%\Programs\Python\*\Scripts` plus `~\.local\bin`. `find_ffmpeg` also checks `~/.spotdl/ffmpeg[.exe]`. Executable lookup via `shutil.which(name, path=...)`. `install_spotdl`: fetch into `<dest>.part`, compare SHA-256, delete on mismatch (`InstallError("checksum mismatch …")`), rename, `chmod 0o755`, on darwin `xattr -d com.apple.quarantine` ignoring failure. The no-asset message names `pipx install spotdl`, `brew install spotdl`, and the spotDL path setting. The real `fetch` (used by the API in Task 6) streams with `httpx` following redirects.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(core): find or install spotDL and ffmpeg`

---

### Task 4: Thread-safe notifications and shutdown hooks in the RPC server

**Files:**
- Modify: `core/rbsync/rpc.py` (`emit` under a `threading.Lock`; `add_closer`, `close`; `serve_forever` calls `close()` in `finally`)
- Test: `core/tests/test_rpc_threads.py` (new)

**Interfaces:**
- Produces: `RpcServer.add_closer(fn: Callable[[], None]) -> None`, `RpcServer.close() -> None` (runs closers once, logs and swallows their exceptions).

- [ ] **Step 1: Write the failing tests**

```python
def test_concurrent_notifications_stay_line_intact():
    out = io.StringIO(); server = RpcServer(service=None, out=out)
    threads = [threading.Thread(target=lambda: [server.notify("x", {"n": "y" * 200}) for _ in range(300)]) for _ in range(4)]
    [t.start() for t in threads]; [t.join() for t in threads]
    lines = out.getvalue().splitlines()
    assert len(lines) == 1200 and all(json.loads(l)["method"] == "x" for l in lines)

def test_serve_forever_runs_closers_on_eof():
    server = RpcServer(service=None, out=io.StringIO()); called = []
    server.add_closer(lambda: called.append(1))
    server.serve_forever(io.StringIO(""))
    assert called == [1]
```

- [ ] **Step 2: Run** → the closer test FAILs (`add_closer` missing). The concurrency test may pass by luck; keep it.
- [ ] **Step 3: Implement** as described; behaviour of `handle_line` unchanged.
- [ ] **Step 4: Run** new file + full suite → PASS.
- [ ] **Step 5: Commit** `feat(core): let the RPC server emit from worker threads and run shutdown hooks`

---

### Task 5: The download queue

**Files:**
- Create: `core/rbsync/downloader.py`
- Test: `core/tests/test_downloader.py` (new)

**Interfaces:**
- Consumes: Task 1 `Cache.record_download/get_downloads`; Task 2 `mp3_bitrate_for`, `measure_audio_kbps`, `encode_mp3_lowq`, `TranscodeError`; Task 3 `ToolMissing`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class TrackRequest:
      spotify_id: str; url: str; name: str; artists: list[str]; album: str; isrc: str; playlist_name: str
  @dataclass(frozen=True)
  class DownloadConfig:
      folder: Path; spotdl: str; ffmpeg: str; client_id: str = ""; client_secret: str = ""
  Runner = Callable[[list[str], threading.Event], tuple[int, str]]      # (returncode, combined output)
  def run_process(args: list[str], cancel: threading.Event) -> tuple[int, str]
  def safe_folder_name(name: str) -> str
  def spotdl_command(cfg: DownloadConfig, url: str, out_dir: Path, fmt: str = "opus") -> list[str]   # fmt "opus" | "m4a"
  def is_rate_limited(output: str) -> bool
  class Downloader:
      def __init__(self, cache: Cache, config: Callable[[], DownloadConfig], notify: Callable[[str, dict], None],
                   run: Runner = run_process, measure=measure_audio_kbps, encode=encode_mp3_lowq) -> None
      def enqueue(self, tracks: list[TrackRequest]) -> list[dict]     # [{"jobId", "spotifyId", "state", "path"}]
      def install(self, task: Callable[[], str]) -> dict              # runs task on the worker; {"jobId": "install"}
      def cancel(self, job_id: str | None = None) -> int
      def resume(self) -> None
      def status(self) -> dict                                        # {"paused": bool, "reason": str, "jobs": [job dicts]}
      def shutdown(self) -> None
  ```
  Notifications: `download.progress` `{jobId, spotifyId, state, message, path}` with state in `queued|downloading|converting|done|failed|cancelled|skipped`; install uses `jobId "install"` and `state` `downloading|done|failed`. Queue state: `download.queue` `{paused, reason}`.

- [ ] **Step 1: Write the failing tests** (fake runner writes a file into the out dir; fake `measure` returns 160; fake `encode` copies source to target and records the kbps)

```python
@pytest.mark.parametrize("name,expected", [
    ("Techno / Warmup: 2026?", "Techno _ Warmup_ 2026_"),
    ("CON", "_CON"), ("trailing...", "trailing"), ("", "Playlist"), ("🔥 Sets", "🔥 Sets")])
def test_safe_folder_name(name, expected): ...

def test_spotdl_command_has_opus_no_conversion_and_secret_only_when_set(tmp_path):
    cmd = spotdl_command(cfg(tmp_path), "https://open.spotify.com/track/x", tmp_path)
    assert cmd[1:3] == ["download", "https://open.spotify.com/track/x"]
    assert ["--format", "opus"] == cmd[cmd.index("--format"):cmd.index("--format") + 2]
    assert "--bitrate" in cmd and cmd[cmd.index("--bitrate") + 1] == "disable"
    assert "--client-secret" not in cmd
    assert "--client-secret" in spotdl_command(cfg(tmp_path, client_id="i", client_secret="s"), "u", tmp_path)

def test_one_track_end_to_end(tmp_path): # → file at <folder>/Warmup/<Artist - Title>.mp3, encode called with 224, record "done", notifications end in "done"
def test_enqueue_skips_queued_and_done(tmp_path): # same id twice in one call + an id with a done record whose file exists → one job, others "skipped"
def test_done_record_with_deleted_file_is_downloaded_again(tmp_path): ...
def test_existing_target_file_is_kept(tmp_path): # target exists → new file discarded, record path = existing
def test_m4a_fallback_when_opus_fails(tmp_path): # opus run rc=1, no file, not rate-limited → one retry with --format m4a → done
def test_failure_continues_queue(tmp_path): # runner rc=1 for track 1 → "failed" with message, track 2 "done"
def test_rate_limit_pauses_and_requeues(tmp_path): # output "HTTP Error 429: Too Many Requests" → paused, job back to "queued"; resume() → done
def test_unwritable_folder_pauses_queue(tmp_path): # folder under a chmod 0o500 dir → paused, reason mentions the folder
def test_missing_tool_pauses_queue(tmp_path): # config() raises ToolMissing("spotdl not found") → paused with that reason
def test_cancel_leaves_no_partial_file(tmp_path): # runner blocks until cancel set → state "cancelled", playlist folder has no audio, temp dir gone
def test_temp_dir_wiped_on_start(tmp_path): # pre-existing <folder>/.rbsync-tmp/old/x.part removed when the first job starts
def test_secret_never_in_notifications(tmp_path): # runner output echoes "--client-secret s3cret" and fails → no notify payload contains "s3cret"
def test_shutdown_cancels_running_job(tmp_path): ...
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_downloader.py -v` → FAIL.
- [ ] **Step 3: Implement.**
  - `safe_folder_name`: replace `<>:"/\|?*` and control chars with `_`; strip trailing dots and spaces; empty → `Playlist`; Windows-reserved stems (`CON PRN AUX NUL COM1-9 LPT1-9`, case-insensitive) get a `_` prefix; cut to 120 characters.
  - `spotdl_command`: `[spotdl, "download", url, "--format", fmt, "--bitrate", "disable", "--output", str(out_dir / "{artists} - {title}.{output-ext}"), "--overwrite", "skip", "--ffmpeg", ffmpeg]` + `["--client-id", id, "--client-secret", secret]` only when both set.
  - `is_rate_limited`: case-insensitive match on `rate limit`, `429`, `too many requests`.
  - `run_process`: `Popen` with stdout+stderr merged, cancel polled every 0.2 s (kill on set), `CREATE_NO_WINDOW` on Windows.
  - Worker: one daemon thread started lazily; jobs keyed by uuid4 hex. Per job: `config()` (ToolMissing → pause); `mkdir` target folder and `.rbsync-tmp/<jobId>` (OSError → pause with `Download folder not writable: <folder>`); run spotDL with `opus`; if it exits non-zero with no file and is not rate-limited, retry once with `m4a` (spec: fallback when no Opus stream exists); exactly one audio file expected in the temp dir; `kbps = mp3_bitrate_for(measure(...))`; encode into temp; move into `<folder>/<safe playlist>/<same stem>.mp3` unless that exists (then keep existing); record; always `rmtree` the job's temp dir. First job of the worker's life wipes `.rbsync-tmp` first.
  - Every notification `message` passes through a scrub that replaces the configured secret with `***`; error messages use the last non-empty output line, scrubbed.
  - `shutdown`: set stop, cancel running, join with 5 s timeout.
- [ ] **Step 4: Run** new file + full suite → PASS.
- [ ] **Step 5: Commit** `feat(core): download queue for missing tracks`

---

### Task 6: RPC methods, settings, and `lowq` on candidates

**Files:**
- Modify: `core/rbsync/api.py` (settings keys; new handlers; register them; create the `Downloader`; `server.add_closer(downloader.shutdown)`)
- Modify: `core/rbsync/serialize.py` (`candidate_to_dict` adds `"comment": candidate.track.comment`)
- Modify: `core/rbsync/persist.py` (`_local_track_to_json` adds `"comment"`; `_local_track_from_json` reads `data.get("comment", "")`)
- Test: `core/tests/test_api_downloader.py` (new)

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces (RPC):
  - `settings.get` adds `downloaderEnabled: bool`, `downloadFolder: str`, `downloaderClientId: str`, `hasDownloaderSecret: bool`, `spotdlPath: str`. Cache keys `downloader_enabled`, `download_folder`, `downloader_client_id`, `downloader_client_secret`, `spotdl_path`.
  - `settings.set` accepts `downloaderEnabled`, `downloadFolder`, `downloaderClientId`, `downloaderClientSecret` (`""` clears), `spotdlPath`.
  - `downloader.status` → `{enabled, spotdl: {path, source}, ffmpeg: str|null, version: "4.6.0", paused, reason, jobs}`
  - `downloader.install` → `{"jobId": "install"}` (installs spotDL if `find_spotdl` finds none, then ffmpeg via `download_ffmpeg` if `find_ffmpeg` finds none)
  - `downloader.enqueue({tracks: [{spotifyId, url, name, artists, album, isrc}], playlistName})` → list from `Downloader.enqueue`; raises `RuntimeError("Downloads are switched off in Settings.")` when disabled
  - `downloader.cancel({jobId?})` → `{cancelled: int}`; `downloader.resume()` → `{paused: false}`
  - `downloads.get({spotifyIds})` → `{spotifyId: {status, path, playlistName, error, exists}}`
  - Candidate dicts gain `comment: str`.

- [ ] **Step 1: Write the failing tests** (reuse the `service`/`server`/`call` pattern from `tests/test_api.py`, copied into the new file; do not edit `test_api.py`)

```python
def test_downloader_defaults(server):
    s = call(server, "settings.get")["result"]
    assert s["downloaderEnabled"] is False
    assert s["downloadFolder"].endswith(os.path.join("Downloads", "rbsync"))
    assert s["hasDownloaderSecret"] is False

def test_secret_is_write_only(server):
    call(server, "settings.set", {"downloaderClientId": "id", "downloaderClientSecret": "s3cret"})
    s = call(server, "settings.get")["result"]
    assert s["hasDownloaderSecret"] is True and "s3cret" not in json.dumps(s)

def test_enqueue_refused_when_disabled(server):
    assert "switched off" in call(server, "downloader.enqueue", {"tracks": [], "playlistName": "x"})["error"]["message"]

def test_downloads_get_reports_existence(server, service, tmp_path):
    f = tmp_path / "a.mp3"; f.write_bytes(b"x")
    service.cache.record_download("sp1", status="done", path=str(f))
    service.cache.record_download("sp2", status="done", path=str(tmp_path / "gone.mp3"))
    r = call(server, "downloads.get", {"spotifyIds": ["sp1", "sp2"]})["result"]
    assert r["sp1"]["exists"] is True and r["sp2"]["exists"] is False

def test_candidate_carries_comment(): ...      # candidate_to_dict on a LocalTrack(comment="lowq") → "comment": "lowq"
def test_stored_plan_without_comment_still_loads(): ...   # _local_track_from_json without "comment" → ""
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** The `Downloader`'s `config` callable resolves tools on every job (`find_spotdl(spotdl_path, paths.tools_dir())`, `find_ffmpeg()`), raising `ToolMissing` with a fix-it sentence; `notify` is `server.notify`. Client id/secret come from the downloader keys only, never from `clientId`.
- [ ] **Step 4: Run** new file + **full suite unchanged** → PASS.
- [ ] **Step 5: Commit** `feat(core): downloader RPC methods and settings`

---

### Task 7: UI plumbing — types, notifications, downloads hook, dialog plugin

**Files:**
- Modify: `ui/src/types.ts` (`Settings` additions; `Candidate.comment: string`; new `DownloadJob`, `DownloadRecord`, `DownloaderStatus`)
- Modify: `ui/src/rpc.ts` (generic `onNotification(method, handler)`; existing `onProgress` untouched)
- Create: `ui/src/downloads.ts`
- Modify: `ui/package.json`, `ui/src-tauri/Cargo.toml`, `ui/src-tauri/src/lib.rs` (`.plugin(tauri_plugin_dialog::init())`), `ui/src-tauri/capabilities/default.json` (`"dialog:allow-open"`)

**Interfaces:**
- Produces:
  ```ts
  export interface DownloadJob { jobId: string; spotifyId: string; state: "queued"|"downloading"|"converting"|"done"|"failed"|"cancelled"|"skipped"; message: string; path: string }
  export interface DownloadRecord { status: "done"|"failed"; path: string; playlistName: string; error: string; exists: boolean }
  export interface DownloaderStatus { enabled: boolean; spotdl: { path: string | null; source: string }; ffmpeg: string | null; version: string; paused: boolean; reason: string; jobs: DownloadJob[] }
  rpc.onNotification(method: string, handler: (params: any) => void): () => void
  export function useDownloads(spotifyIds: string[]): {
    jobs: Map<string, DownloadJob>; records: Map<string, DownloadRecord>; status: DownloaderStatus | null;
    enqueue(playlistName: string, tracks: SpotifyTrack[]): Promise<void>; cancel(jobId?: string): Promise<void>; resume(): Promise<void>; install(): Promise<void>
  }
  ```
  In HTTP dev mode (`!isTauri()`), `useDownloads` polls `downloader.status` every 1.5 s while any job is queued/downloading/converting. On a `done` notification it refreshes `downloads.get` for that id.

- [ ] **Step 1: Implement** the files above.
- [ ] **Step 2: Verify** `cd ui && npm install && npm run typecheck && npm run lint` → no errors; `cd ui/src-tauri && cargo check` → builds.
- [ ] **Step 3: Commit** `feat(ui): downloader types, notifications and dialog plugin`

---

### Task 8: Settings — Downloads section

**Files:**
- Modify: `ui/src/components/SettingsPanel.tsx` (new section after the existing ones; existing fields unchanged)

**Interfaces:**
- Consumes: Task 6 settings keys; Task 7 `useDownloads().install/status`.

- [ ] **Step 1: Implement** the section: toggle **Download missing tracks (spotDL)**; when switched on, call `settings.set` then `downloader.install` if `status.spotdl.path` is null. Quality note, exact copy: "Downloads come from YouTube Music: Opus around 160 kbps, converted to an mp3 bitrate that matches it and labelled lowq. Fine for practice and emergencies; buy the track for club use." Folder field with **Choose…** (`open({ directory: true })` from `@tauri-apps/plugin-dialog`). Optional spotDL client id + secret (secret input shows "saved" when `hasDownloaderSecret`, never the value). Optional spotDL path. Status line: `spotDL 4.6.0 — <path> (<source>)` / `not installed`, and `ffmpeg <path>` / `not found`. Hidden toggle disabled with the status reason while installing.
- [ ] **Step 2: Verify** typecheck + lint pass. Manual (dev bridge, `RBSYNC_FAKE_SPOTIFY=1`, see README "Working on the interface"): toggle on → install runs, status line shows the path; secret saved shows "saved"; reload keeps settings.
- [ ] **Step 3: Commit** `feat(ui): downloads section in Settings`

---

### Task 9: Track table, Download button, Download panel

**Files:**
- Modify: `ui/src/components/TrackTable.tsx` (new optional props; badges; menu items appended; head button)
- Create: `ui/src/components/DownloadPanel.tsx`
- Modify: `ui/src/App.tsx` (call `useDownloads` for the active plan's ids, pass props, open the panel, add a StatusBar button **Downloads** only when the feature is on)
- Modify: `ui/src/components/StatusBar.tsx` (optional `onDownloads?: () => void`, button rendered only when provided)
- Modify: `ui/src/App.css` (badge styles reuse the existing `.band` look)

**Interfaces:**
- Consumes: Task 7 `useDownloads`, types.
- Produces: `TrackTable` optional props `downloads?: { enabled: boolean; jobs: Map<string, DownloadJob>; records: Map<string, DownloadRecord>; onDownload(rows: TrackPlan[]): void }`. When the prop is absent, the table renders exactly as today.

- [ ] **Step 1: Implement.**
  - Head (`.bulk`): button `Download N missing` when `enabled` and N > 0; N = rows with `band === "reject"` minus ids with a job in queued/downloading/converting or a `done` record whose `exists` is true. Disabled with tooltip "Install spotDL in Settings first" when the status has no spotDL path.
  - Badges in the state column after the existing band: `queued`, `downloading…`, `converting…`, `downloaded` (record done + exists), `download failed` (tooltip = error); on matched rows whose best candidate's `comment` contains `lowq` (case-insensitive word match): `lowq`.
  - Context menu: append `Download` (missing rows, single or many, when enabled) and, for `downloaded` rows, `Show download in Finder` (existing `revealItemInDir`). Existing items untouched and in the same order.
  - `DownloadPanel`, following `HistoryPanel`'s structure: list of jobs with state and message, **Cancel all**, **Resume** when paused (with the reason), and per finished playlist "N tracks in `<folder>`" with **Show in Finder**.
- [ ] **Step 2: Verify** typecheck + lint. Manual with the dev bridge and real spotDL on this Mac: plan a fake playlist, press `Download 2 missing` → badges move queued → downloading → converting → downloaded; file in `~/Downloads/rbsync/<playlist>/` with comment `lowq` and the expected bitrate (`ffprobe`); press again → button gone/N excludes them; cancel mid-download → no file left; feature off → table identical to before.
- [ ] **Step 3: Commit** `feat(ui): download missing tracks from the track table`

---

### Task 10: Buy and search links

**Files:**
- Create: `ui/src/findLinks.ts`
- Modify: `ui/src/components/TrackTable.tsx` (append Find items), `ui/src/components/TrackInfoPanel.tsx` (same links as a row of chips)

**Interfaces:**
- Produces:
  ```ts
  export interface FindLink { label: string; url: string }
  export function findLinks(track: { artists: string[]; name: string }): FindLink[]
  ```
  Query = `searchQueryFor(track)` from `ui/src/clipboard.ts`, URI-encoded. Order and URLs:
  - Beatport `https://www.beatport.com/search?q=<q>`
  - Bandcamp `https://bandcamp.com/search?q=<q>&item_type=t`
  - Traxsource `https://www.traxsource.com/search?term=<q>`
  - Juno Download `https://www.junodownload.com/search/?q%5Ball%5D%5B%5D=<q>`
  - Discogs `https://www.discogs.com/search/?q=<q>&type=all`

- [ ] **Step 1: Implement.** Menu items `Find on Beatport` … `Find on Discogs` appended after the existing copy/Spotify items for single missing rows and single `lowq` rows, opened with `openUrl`. Available whether or not the downloader is on. The existing `Copy "Artist - Title"` item stays the Soulseek path, unchanged.
- [ ] **Step 2: Verify** typecheck + lint; manual: right-click a missing row → five Find items under the existing ones; Beatport opens with the track's search; works with the downloader off.
- [ ] **Step 3: Commit** `feat(ui): buy and search links for missing and lowq tracks`

---

### Task 11: Docs and end-to-end check in the built app

**Files:**
- Modify: `README.md` (new section "Downloading missing tracks" after "Coverage and the wantlist"; update "Status" to drop "assisted downloading of wantlist tracks" from not-built)

- [ ] **Step 1: Write** the README section: off by default; what it downloads and where; quality (Opus ~160 → matched mp3, `lowq` comment, why not 320); optional own Spotify client id + secret against rate limits; Intel Macs need `pipx install spotdl`; Find links; downloads never touch rekordbox.
- [ ] **Step 2: Verify** full core suite `cd core && .venv/bin/python -m pytest` → PASS with every pre-existing test unmodified (`git diff main -- core/tests` shows only new files).
- [ ] **Step 3: Verify** build: `./scripts/build-app.sh` succeeds; in the built app on this Mac, switch the feature on, download one playlist's missing tracks, confirm folder, tags, `lowq`, bitrate; quit mid-download and confirm no orphan `spotdl` process (`pgrep -f spotdl` empty) and no partial file.
- [ ] **Step 4: Commit** `docs: downloading missing tracks`
