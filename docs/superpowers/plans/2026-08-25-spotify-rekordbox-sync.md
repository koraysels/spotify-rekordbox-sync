# Spotify → Rekordbox Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A distributable desktop app that recreates selected Spotify playlists inside rekordbox's `master.db`, populated with matching tracks from the user's existing local collection, and reports what is missing.

**Architecture:** Tauri v2 shell (Rust glue) hosts a React/TypeScript UI and spawns a PyInstaller-frozen Python sidecar. The sidecar owns all rekordbox access through pyrekordbox and speaks line-delimited JSON-RPC 2.0 over stdio. No UI code ever touches `master.db`.

**Tech Stack:** Python 3.12, pyrekordbox 0.4.4, SQLAlchemy 2, pytest, Tauri v2, Rust, React 18, TypeScript 5, Vite.

**Spec:** `docs/superpowers/specs/2026-08-25-spotify-rekordbox-sync-design.md`

## Global Constraints

- Python 3.12. All Python lives in `core/`, venv at `core/.venv`.
- All UI code is TypeScript. No plain JavaScript anywhere.
- `master.db` is NEVER opened for writing in a test. Tests copy it first.
- No test may require network access or a live Spotify token.
- Before any write to `master.db`: rekordbox-not-running check, then backup, then a single transaction.
- Matching thresholds are configuration, never hardcoded at call sites: `auto_accept=0.88`, `reject=0.62` are defaults only.
- Track duration in rekordbox `DjmdContent.Length` is **seconds**; Spotify `duration_ms` is **milliseconds**. Convert at the boundary.
- Playlists are written under a single rekordbox playlist folder named `Spotify`.

---

### Task 1: Project scaffold and normalization primitives

**Files:**
- Create: `core/pyproject.toml`
- Create: `core/rbsync/__init__.py`
- Create: `core/rbsync/normalize.py`
- Test: `core/tests/test_normalize.py`

**Interfaces:**
- Produces: `normalize_title(s: str) -> str`, `normalize_artist(s: str) -> str`, `split_artists(s: str) -> list[str]`, `extract_mix_tags(s: str) -> set[str]`

- [ ] **Step 1: Write failing tests** covering the real messy cases found in the library spike: `(Original Version)`, `(OFFICIAL SONG)`, `[Prod. By Menace]`, `Wiz Khalifa Ft. Travis Scott`, leading track numbers `03 `, diacritics `Roméo Elvis`.
- [ ] **Step 2: Run** `core/.venv/bin/pytest core/tests/test_normalize.py -v` — expect ImportError.
- [ ] **Step 3: Implement** `normalize.py`.
- [ ] **Step 4: Run tests** — expect PASS.
- [ ] **Step 5: Commit** `feat: text normalization for track matching`.

---

### Task 2: Matching engine

**Files:**
- Create: `core/rbsync/models.py`
- Create: `core/rbsync/matcher.py`
- Test: `core/tests/test_matcher.py`

**Interfaces:**
- Consumes: everything from `normalize.py`.
- Produces: `SpotifyTrack`, `LocalTrack`, `MatchCandidate`, `MatchResult`, `Band`, `MatchConfig`, `TrackIndex(tracks).search(spotify_track) -> list[MatchCandidate]`, `match_track(track, index, config) -> MatchResult`.

- [ ] **Step 1: Write failing tests:** ISRC equality forces accept; duration delta > 30s rejects despite identical title; `Radio Edit` vs `Extended Mix` never auto-accepts; exact artist+title+duration auto-accepts; banding respects configured thresholds.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** inverted token index + duration bucketing + weighted scoring (title 0.55, artist 0.30, duration 0.15) + hard rules.
- [ ] **Step 4: Run tests** — expect PASS.
- [ ] **Step 5: Commit** `feat: track matching engine`.

---

### Task 3: Cache (decisions, selection, history)

**Files:**
- Create: `core/rbsync/cache.py`
- Test: `core/tests/test_cache.py`

**Interfaces:**
- Produces: `Cache(path)` with `remember_decision(spotify_id, content_id, accepted)`, `get_decision(spotify_id) -> Decision | None`, `set_selected_playlists(ids)`, `get_selected_playlists() -> list[str]`, `record_sync(playlist_id, stats)`, `get_sync_history(playlist_id)`.

- [ ] **Step 1: Write failing tests** — decisions survive reopen; rejections are remembered as rejections, not absence; selection round-trips.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** with stdlib `sqlite3`, schema created on init, `PRAGMA user_version` for migrations.
- [ ] **Step 4: Run tests** — expect PASS.
- [ ] **Step 5: Commit** `feat: local decision and selection cache`.

---

### Task 4: Rekordbox read layer

**Files:**
- Create: `core/rbsync/rekordbox.py`
- Test: `core/tests/test_rekordbox_read.py`

**Interfaces:**
- Produces: `RekordboxLibrary.open(path=None)`, `.load_tracks() -> list[LocalTrack]`, `.list_playlists() -> list[RbPlaylist]`, `.close()`.

- [ ] **Step 1: Write failing tests** against a copied fixture DB; skip cleanly when no rekordbox install is present so CI stays green.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** using `Rekordbox6Database(path, unlock=True)`, mapping `DjmdContent` → `LocalTrack` (ID, title, artist, length seconds, ISRC, folder path, filename).
- [ ] **Step 4: Run tests** — expect PASS.
- [ ] **Step 5: Commit** `feat: rekordbox collection reader`.

---

### Task 5: Rekordbox safety gate

**Files:**
- Modify: `core/rbsync/rekordbox.py`
- Test: `core/tests/test_safety.py`

**Interfaces:**
- Produces: `RekordboxRunning` and `BackupFailed` exceptions, `is_rekordbox_running() -> bool`, `backup_database(db_path, backup_dir) -> Path`, `prune_backups(backup_dir, keep=10)`.

- [ ] **Step 1: Write failing tests** — refuses when the process check reports running; backup byte count must equal source; corrupted/short backup raises `BackupFailed`; pruning keeps exactly the newest 10.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement.** Process detection via `psutil` matching `rekordbox` case-insensitively.
- [ ] **Step 4: Run tests** — expect PASS.
- [ ] **Step 5: Commit** `feat: rekordbox write safety gate`.

---

### Task 6: Rekordbox playlist writes

**Files:**
- Modify: `core/rbsync/rekordbox.py`
- Test: `core/tests/test_rekordbox_write.py`

**Interfaces:**
- Produces: `.ensure_folder(name) -> RbPlaylist`, `.ensure_playlist(name, parent) -> RbPlaylist`, `.playlist_content_ids(playlist) -> list[str]`, `.apply_plan(plan: SyncPlan) -> ApplyResult`.

- [ ] **Step 1: Write failing tests** against a **copy** of a real master.db: creating a playlist under `Spotify` yields a readable playlist; adds produce song rows in order; opt-in removals delete only the named rows; an exception mid-apply leaves the DB unchanged.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** on top of `create_playlist_folder` / `create_playlist` / `add_to_playlist` / `remove_from_playlist`, one commit per apply.
- [ ] **Step 4: Run tests** — expect PASS.
- [ ] **Step 5: Commit** `feat: rekordbox playlist writes`.

---

### Task 7: Spotify client (PKCE + fetch)

**Files:**
- Create: `core/rbsync/spotify.py`
- Test: `core/tests/test_spotify.py`

**Interfaces:**
- Produces: `build_authorize_url(client_id, redirect_uri, verifier) -> str`, `exchange_code(...) -> Tokens`, `refresh(...) -> Tokens`, `SpotifyClient(tokens).list_playlists()`, `.playlist_tracks(playlist_id)` (both fully paged).

- [ ] **Step 1: Write failing tests** using recorded JSON fixtures and a stub transport — paging follows `next` until exhausted; local files and podcast episodes are skipped; ISRC is read from `external_ids`; PKCE challenge is correct S256 of the verifier.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** with `httpx`; retry on HTTP 429 honoring `Retry-After`.
- [ ] **Step 4: Run tests** — expect PASS.
- [ ] **Step 5: Commit** `feat: spotify client with PKCE auth`.

---

### Task 8: Sync planner

**Files:**
- Create: `core/rbsync/sync.py`
- Test: `core/tests/test_sync.py`

**Interfaces:**
- Produces: `SyncPlan`, `PlaylistPlan`, `TrackPlan`, `plan_sync(spotify_playlists, library, cache, config) -> SyncPlan`, `coverage(plan) -> Coverage`, `wantlist(plan) -> list[SpotifyTrack]`.

- [ ] **Step 1: Write failing tests** — cached accept skips re-matching; cached reject keeps the track unmatched instead of re-proposing; additive by default so an absent Spotify track is not marked for removal unless removals are enabled; coverage percentage is matched/total.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests** — expect PASS.
- [ ] **Step 5: Commit** `feat: sync planner with coverage and wantlist`.

---

### Task 9: JSON-RPC sidecar

**Files:**
- Create: `core/rbsync/rpc.py`
- Create: `core/rbsync/__main__.py`
- Test: `core/tests/test_rpc.py`

**Interfaces:**
- Produces: methods `ping`, `auth.begin`, `auth.complete`, `library.load`, `playlists.list`, `playlists.setSelected`, `sync.plan`, `sync.apply`, `review.decide`, `wantlist.export`; progress via `notify(method, params)`.

- [ ] **Step 1: Write failing tests** — a request yields a matching `id`; unknown methods return JSON-RPC error `-32601`; exceptions become error objects, never a crashed process; progress notifications carry no `id`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** line-delimited JSON over stdin/stdout.
- [ ] **Step 4: Run tests** — expect PASS.
- [ ] **Step 5: Commit** `feat: json-rpc sidecar`.

---

### Task 10: CLI entry point

**Files:**
- Create: `core/rbsync/cli.py`
- Test: `core/tests/test_cli.py`

**Interfaces:**
- Produces: `rbsync status`, `rbsync playlists`, `rbsync plan`, `rbsync apply`, `rbsync wantlist`.

- [ ] **Step 1: Write failing tests** — `status` reports library path, track count and whether rekordbox is running; `apply` refuses without `--yes`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** with `argparse`.
- [ ] **Step 4: Run tests** — expect PASS.
- [ ] **Step 5: Commit** `feat: cli entry point`.

---

### Task 11: Tauri shell + React UI

**Files:**
- Create: `ui/` (Vite + React + TS), `src-tauri/` (Tauri v2)
- Create: `ui/src/rpc.ts`, `ui/src/App.tsx`, `ui/src/components/PlaylistList.tsx`, `ui/src/components/TrackTable.tsx`, `ui/src/components/BottomBar.tsx`

- [ ] **Step 1:** Scaffold Vite React-TS app and Tauri v2 project; register the Python binary as a sidecar.
- [ ] **Step 2:** Implement `rpc.ts` typed client over the sidecar.
- [ ] **Step 3:** Master-detail layout: checkbox playlist list left, track table right, bottom bar with `Sync selected (N)` disabled at 0.
- [ ] **Step 4:** Bulk actions — shift-click range, select-all-in-band, bulk accept/reject.
- [ ] **Step 5:** `npm run build` must typecheck clean.
- [ ] **Step 6: Commit** `feat: tauri shell and react ui`.

---

### Task 12: Packaging

**Files:**
- Create: `core/build_sidecar.sh`, `.github/workflows/build.yml`, `README.md`

- [ ] **Step 1:** PyInstaller onefile build of the sidecar, named for the Tauri target triple.
- [ ] **Step 2:** `cargo tauri build` producing a `.dmg`.
- [ ] **Step 3:** README covering Spotify Client ID setup, the rekordbox-closed requirement, and the Cloud Library Sync warning.
- [ ] **Step 4: Commit** `chore: packaging and docs`.
