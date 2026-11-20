# Download missing tracks with spotdl

Date: 2026-11-20
Status: draft, awaiting approval

## Intent

rbsync already tells you which tracks of a Spotify playlist you do not own
(the **missing** band, the wantlist). Today that list ends at a CSV. This
feature closes the gap: with one button, rbsync downloads those tracks with
[spotDL](https://github.com/spotDL/spotify-downloader) into a folder on disk,
one subfolder per Spotify playlist, fully tagged.

From there the user takes over with their own workflow. The author drags the
folder into Apple Music, which copies and sorts files onto an external drive,
and rekordbox picks them up via its iTunes node. Other users drag straight
into rekordbox or a file manager. rbsync does not assume any of these: not
every user works through iTunes/Music.

The next rbsync plan matches the tracks once they are in the rekordbox
collection.

## Goals

- Optional feature, off by default, switched on in Settings.
- A button downloads the missing tracks of the active playlist; a per-track
  action downloads one.
- Files land in `<download folder>/<Spotify playlist name>/` with complete
  tags (title, artists, album, track number, artwork, ISRC).
- Progress is visible per track; the job is cancellable.
- Downloads never block the rest of the app (plan, apply, browse).
- Works on macOS (arm64), Windows, and wherever `spotdl` is on `PATH`.
- Downloads are mp3 320 CBR labelled `lowq`: a stopgap, not a replacement for
  bought files.
- Buy and search links (Beatport, Bandcamp, Traxsource, Juno, Discogs) on
  missing and `lowq` tracks, so stopgaps get replaced. Soulseek keeps working
  through the existing copy-query item.
- Every existing feature keeps working exactly as it does now (see
  "Existing features: unchanged").

## Non-goals

- Adding files to Apple Music, iTunes, or rekordbox's `master.db` in this
  phase. The user imports them. Adding to Music is planned as a later,
  optional setting (see "Later phase"); collection import is a possible
  future design.
- Automatic downloading when a plan completes. Always an explicit button.
- Choosing audio sources other than spotDL's YouTube Music default.

## Anti-goals

- Bulk work the user did not ask for. A button downloads exactly the tracks it
  names, with the count on the button. Nothing starts on its own, and there is
  no "download everything across all playlists" button.
- A download job that freezes the UI or stalls RPC calls (the core answers one
  JSON-RPC call at a time; see "Process model").
- A YouTube download that can pass for a bought file. Every download is
  labelled `lowq`, in the file and in rbsync, so it is always clear what still
  needs replacing.
- Downloading the same track twice because it is still "missing" while the
  user has not imported it yet.

## Constraints

- spotDL 4.6.0 ships standalone binaries: `spotdl-4.6.0-darwin` (arm64 Mach-O,
  44 MB), `spotdl-4.6.0-win32.exe`, `spotdl-4.6.0-linux`. No Intel macOS
  binary: Intel Macs use a `spotdl` found on `PATH`, otherwise the feature
  reports itself unavailable with install instructions.
- spotDL needs ffmpeg. Use the one on `PATH` when present, otherwise run
  `spotdl --download-ffmpeg` once (installs into spotDL's own directory).
- spotDL calls the Spotify API with its own shared client credentials, which
  are frequently rate-limited. YouTube can also throttle a client for up to
  24 h. Errors must be shown per track, not swallowed.
- rbsync's Spotify sign-in uses PKCE without a client secret, so rbsync's
  tokens cannot be handed to spotDL.
- Source quality. Without YouTube Music Premium (the user has none), YouTube
  offers at best Opus itag 251 (~130–160 kbps VBR) or AAC 128 kbps. spotDL's
  own docs: never above 128 kbps except 256 kbps M4A with Premium. Using
  yt-dlp directly does not help: spotDL already uses yt-dlp, and the limit is
  what YouTube serves. Opus ~160 is roughly comparable to mp3 192–256; it is
  not 320.
- rekordbox and CDJs do not play Opus, so the file must be converted. Target:
  **mp3 320 kbps CBR**. mp3 is playable on every CDJ; CBR because older CDJs
  can mis-seek and drift beatgrids on VBR mp3; 320 keeps the second lossy
  generation as transparent as possible. The real quality stays that of the
  Opus source. The UI says so where the feature is switched on.

## Existing features: unchanged

This feature is an addition, not a replacement. Everything below keeps
working exactly as it does in 0.3.5, with the downloader on or off. The
"touches" column lists the only places this design adds anything; "no" means
the code path is not modified.

| Existing feature | Where | Touches |
|---|---|---|
| Spotify connect (PKCE, own Client ID, keychain tokens) | `ConnectPanel`, `spotify.py`, `lib.rs` `oauth_listen` | no (spotDL gets its own optional id/secret pair) |
| Playlist list + selection, cached playlists | `PlaylistList`, `playlists.*` RPC | no |
| Sync window (Spotify left, rekordbox tree right) | `SyncWindow`, `syncWindow.ts` | no |
| Plan: matching, bands matched/review/missing, thresholds | `matcher.py`, `sync.py`, `sync.plan` | no |
| Stored plans + fingerprint invalidation | `app.plan_fingerprint`, `plans.cached` | no |
| Apply into `master.db` (rekordbox closed, backup, one transaction, `Spotify` folder) | `app.apply`, `ApplyDialog`, `BottomBar` | no |
| Review decisions, candidate picker, accept/reject/undo, Decisions panel | `CandidatePicker`, `DecisionsPanel`, `review.*`, `decisions.*` | no |
| Track table: columns, sorting, filters, track info | `TrackTable`, `TrackInfoPanel` | adds badges (`queued/downloading/downloaded/failed/lowq`) and menu items; existing columns and items unchanged |
| Track context menu (Track info, Choose match, Accept, Reject, Undo, Show file, Copy "Artist - Title", Copy Spotify link, Open in Spotify, Copy names) | `TrackTable.menuFor` | adds `Download` and Find links after existing items |
| File availability (offline / no file), reveal file | `tracks.verify`, `RekordboxPanel` | no |
| Wantlist export CSV + txt, WantlistBanner copy/reveal | `wantlist.*`, `WantlistBanner` | no; downloaded tracks stay on the wantlist until matched |
| Energy / dance / mood (ReccoBeats), Energy panel, My Tag writes | `features.py`, `EnergyPanel`, `energy.*` | no |
| Backups, baseline, restore | `BackupsPanel`, `backups.*` | no |
| History | `HistoryPanel`, `history.list` | no |
| Playlist-tree repair | `rekordbox.repair` | no |
| Settings (Client ID, thresholds, removals, only syncable, tag features) | `SettingsPanel`, `settings.*` | adds a Downloads section; existing keys unchanged |
| Updater, banner, restart | `UpdateBanner`, updater plugin | no |
| CLI (`rbsync status/playlists/select/plan/apply/history/wantlist`) | `cli.py` | no |
| HTTP dev bridge | `httpbridge.py` | no (UI polls `downloader.status` there) |
| JSON-RPC server | `rpc.py` | `emit` gets a lock; behaviour unchanged |
| Build: frozen core sidecar, Tauri bundle, release workflow | `build_sidecar.sh`, `tauri.conf.json` | no new `externalBin`; adds `tauri-plugin-dialog` |

Rule for the builder: the existing test suite (`core/tests`) must pass
unmodified. Any change to an existing test is a sign this rule is being
broken and needs the user's say.

## Approaches considered

**Audio quality (chosen by the user)**

- **Opus source → mp3 320 CBR, labelled `lowq` (chosen).** Best a free
  account gets, in a format every CDJ plays, clearly marked as a stopgap.
- Keep AAC 128 m4a without re-encode. No second generation, but clearly
  worse than the Opus source. Rejected.
- Require YouTube Music Premium for 256 kbps AAC. The user has no Premium.
  Rejected.
- Use yt-dlp directly instead of spotDL. Same YouTube streams, and the
  Spotify-to-YouTube matching and tagging would have to be rebuilt. Rejected.

**Where downloads go**

- **Folder on disk, user imports (chosen by the user).** Works for every
  workflow and platform, no permissions, smallest build.
- Add to Apple Music automatically via AppleScript, plus a Music playlist per
  Spotify playlist. One step fewer for Music users, but macOS only, needs the
  Automation permission, and assumes a workflow not every user has. Not the
  default; planned as an opt-in setting in a later phase.
- Import into `master.db` via `pyrekordbox.add_content`. Fully automatic, but
  `add_content` fills only path and filename; artist/album rows, length and
  bitrate would be hand-written, tracks arrive unanalysed, and it adds write
  risk to the user's library. Deferred.

**How spotDL is delivered** (my call)

- **Fetched when the feature is switched on (chosen).** Pinned version and
  SHA-256, stored in rbsync's config dir. Nobody who leaves it off pays for it.
- Bundled as a Tauri `externalBin`. +44 MB for everyone, and breaks the
  Intel macOS build (no binary for that triple). Rejected.
- Only `spotdl` from `PATH`. Least work, but every user installs and
  maintains it. Kept as the fallback for Intel Macs and development.

## Design

### Settings

New keys in the existing `settings.get` / `settings.set` (stored via
`cache.set_setting`):

- `downloaderEnabled` (bool, default false). Turning it on triggers the spotDL
  install (below) and shows the quality note.
- `downloadFolder` (path, default `~/Downloads/rbsync`). Changeable with a
  folder picker.
- `downloaderClientId` + `downloaderClientSecret` (optional pair, used only
  by spotDL; my call). A separate pair because a secret belongs to one
  registered Spotify app, and rbsync's own Client ID may be the bundled one,
  whose secret the user does not have. When both are set, spotDL gets
  `--client-id … --client-secret …` and uses the user's own quota instead of
  its shared, often rate-limited credentials. `settings.get` returns only
  `hasDownloaderSecret`, never the secret. Stored in the `settings` table like
  the rest; never logged.
- `spotdlPath` (optional). An explicit binary path, overriding discovery.

A status line under the toggle: spotDL version and path, ffmpeg found or not.

### Finding binaries (my call)

A Finder-launched app and its sidecar get launchd's minimal `PATH`, which has
no Homebrew or pipx directories. Discovery order for `spotdl` and `ffmpeg`:
explicit `spotdlPath` setting; the installed binary in `<config_dir>/tools/`
(spotdl only); `PATH`; then known locations: `/opt/homebrew/bin`,
`/usr/local/bin`, `~/.local/bin`, and on Windows `%LOCALAPPDATA%` pipx shims.
spotDL's own ffmpeg (`~/.spotdl/ffmpeg`) counts as found. Only when none is
found does enabling the feature run `spotdl --download-ffmpeg`. ffmpeg's
resolved path is passed with `--ffmpeg`.

### Installing spotDL

`downloader.install` (RPC, runs on the downloader worker, not the RPC thread)
downloads the platform binary from
`https://github.com/spotDL/spotify-downloader/releases/download/v4.6.0/<asset>`
into `<config_dir>/tools/`, verifies a SHA-256 pinned in code per asset,
makes it executable, and on macOS clears the quarantine attribute. On hash
mismatch the file is deleted and the error shown. On Intel macOS (no asset),
it uses discovery (below) instead, and if nothing is found says how to
install spotDL (`pipx install spotdl` / `brew install spotdl`) or point
`spotdlPath` at a binary.

Upgrading spotDL means changing the pinned version and hashes in a release.

### Process model

The core's RPC loop handles one call at a time, so a download job must not
run inside a handler.

- One `Downloader` in the core owns a single background worker thread and a
  FIFO queue.
- `downloader.enqueue({playlistName, tracks: [{spotifyId, url, name,
  artists, album, isrc}]})` adds tracks and returns immediately with their job
  ids. The UI sends full track data (my call): the core's held plan is cleared
  by `sync.apply`, so resolving ids against it would break the button right
  after an Apply.
- The worker runs one spotDL subprocess per track (my call): it keeps
  per-track progress, cancel and result mapping simple. The onefile binary
  unpacks on each start (a few seconds), which is accepted next to download
  time. Reports go out as JSON-RPC notifications `download.progress`
  (`{jobId, spotifyId, state, message, path?}`), with states
  `queued | downloading | done | failed | cancelled` plus a queue-level
  `paused` state.
- On Windows the subprocess starts with `CREATE_NO_WINDOW`.
- `RpcServer.emit` gets a lock, because notifications now come from two
  threads.
- `downloader.status` returns the queue, the paused flag and recent results;
  `downloader.cancel` (one job id, or all) kills the running subprocess and
  drops queued jobs; `downloader.resume` resumes a paused queue.
- The UI's rpc client routes `download.progress` to subscribers the way it
  already routes `progress`. The HTTP dev bridge does not deliver
  notifications, so in browser dev mode the UI polls `downloader.status`.

**Queue lifetime (my call).** The queue lives in memory only. Quitting the app
loses queued jobs; the user presses the button again, and already downloaded
tracks are skipped. On shutdown (stdin closes) the worker kills the running
spotDL child so no orphan keeps downloading. spotDL writes into a per-job
temp directory inside `<downloadFolder>/.rbsync-tmp/`; only a finished file is
moved into the playlist folder. A cancelled or killed run leaves at most a temp
directory, which is wiped on the next worker start. This also keeps
`--overwrite skip` from skipping over a half-written file.

The worker never touches `master.db`, so it is safe while rekordbox is open
and alongside plan/apply.

### One track, end to end

1. Input from `downloader.enqueue`: Spotify track (url, id, name, artists,
   album, ISRC) and the Spotify playlist name the button was pressed for.
2. Target folder `<downloadFolder>/<playlist name>/`, with the playlist name
   made filesystem-safe.
3. Run, into the job's temp directory:
   `spotdl download <spotify-track-url> --format mp3 --bitrate 320k
   --output "<tmp>/{artists} - {title}.{output-ext}" --overwrite skip
   --ffmpeg <path> [--client-id … --client-secret …]`
   with yt-dlp told to prefer the Opus stream (`--yt-dlp-args` with
   `-f 251/bestaudio`), so the conversion starts from the best free source,
   not AAC 128. spotDL writes title, artists, album, track number, artwork and
   ISRC.
4. Label the file: set the ID3 comment (`COMM`) to `lowq` (my call: comment,
   because rekordbox imports it into its Comments column, where it is
   searchable and sortable). Write it after spotDL finishes, with ffmpeg
   metadata copy or mutagen, replacing whatever comment spotDL wrote.
5. Verify exactly one audio file appeared, move it into the target folder
   (if a file with that name already exists there, keep it and record that
   path), record the result. This is the "after download" step where the
   later Music phase hooks in.

### Remembering downloads

New cache table `downloads`:
`spotify_id (pk), status (done|failed), path, playlist_name, error,
created_at`. The later Music phase adds a nullable `music_persistent_id`
column (my call: added then, through the cache's normal schema setup, rather
than an unused column now).

- A track with `done` whose file still exists is not offered again while it
  is still missing in rbsync. Its row shows **downloaded** (meaning: waiting
  for you to import it), and its file can be revealed.
- If the user deleted the file, the track is offered again.
- A track wanted by several playlists is downloaded once, into the folder of
  the playlist the button was pressed for; in other playlists it shows
  **downloaded** with that path.
- Once a later plan matches it, it leaves the missing band and the label goes
  with it.
- `failed` rows show the error and can be retried.

### UI

- **Sync view, active playlist:** button `Download N missing` when the feature
  is on and N > 0 (N excludes tracks already downloaded). Disabled with a
  reason when spotDL is not installed.
- **Track table, missing rows:** context-menu item `Download`; row badge
  `queued` / `downloading…` / `downloaded` / `download failed` (error as
  tooltip); `downloaded` rows get the existing reveal-file action.
- **Download panel** (follows the backups/history panel pattern): queue with
  per-track state, cancel all, and when done: "N tracks in
  `<folder>/<playlist>`" with **show in Finder/Explorer**.
- **Matched rows whose rekordbox comment contains `lowq`** (my call): badge
  `lowq` and the same Find menu as missing rows (below), so a set built on
  stopgap files shows what still needs buying. `LocalTrack.comment` is
  already loaded from `master.db`, so this needs no extra reads.
- **Settings:** the toggle, quality note, download folder (picker via
  `tauri-plugin-dialog`, to be added), optional spotDL client id + secret,
  optional spotDL path, status line.

### Buy and search links

Independent of the downloader: available even with it switched off, on every
missing row and every `lowq` row.

- Context-menu submenu **Find** (and the same links in the track info panel)
  opening the system browser with a search for `<artists> <title>`, cleaned
  with the existing title normalizer (drop `feat.`, `(Original Mix)` noise,
  keep remix/edit names):
  - Beatport `https://www.beatport.com/search?q=…`
  - Bandcamp `https://bandcamp.com/search?q=…&item_type=t`
  - Traxsource `https://www.traxsource.com/search?term=…`
  - Juno Download `https://www.junodownload.com/search/?q%5Ball%5D%5B%5D=…`
  - Discogs `https://www.discogs.com/search/?q=…&type=all`
- **Soulseek stays as it is today**: the existing context-menu item
  `Copy "<Artist> - <Title>"` (built by `searchQueryFor` in
  `ui/src/clipboard.ts`) and the wantlist's `Artist - Title` text export are
  the Soulseek path, unchanged. Soulseek clients have no standard search URL.
  The store links use the same `searchQueryFor` string, so every search
  starts from the same query.
- The Find links are added after the existing copy/Spotify items; no existing
  item is removed, renamed or reordered.
- The store list is a fixed constant in the UI for now (my call); making it
  configurable can come later.

### Errors

Per track; the queue continues. A rate-limit error from spotDL pauses the
queue (my call): the panel shows "Paused: rate-limited by Spotify/YouTube"
with a **Resume** button and the hint to set your own client id + secret.
Nothing resumes on its own; the paused state lasts for the session only.
A missing spotDL or ffmpeg stops the queue with how to fix it.

## Later phase: add to Apple Music (opt-in setting)

Not built now. Recorded so phase 1 leaves room for it.

- Setting `addToMusic` (macOS only, default off).
- After a file is verified (step 4 above), the worker runs
  `tell application "Music" to add POSIX file …` via `osascript` (paths
  passed as arguments, not interpolated), reads back `location` and
  `persistent ID`, and duplicates the track into a Music playlist
  `rbsync/<Spotify playlist name>`, which rekordbox shows in its iTunes node.
- A track already downloaded for another playlist is added to that
  playlist's Music playlist via its stored `music_persistent_id`, without
  downloading again.
- If Music copied the file into its media folder (the returned `location`
  differs from the downloaded file), the downloaded copy is removed. If not
  (Music's "Copy files to Music Media folder" is off), the file stays and the
  user is told how to enable copying.
- Handles the Automation permission prompt and its denial (`-1743`).

Phase 1 requirement for this: the per-track pipeline has a clear
"after download" step where this can be added without restructuring the
worker.

## Testing

- Unit: queue and cancel logic with a fake spotDL command; result parsing;
  `downloads` table; "missing minus downloaded" count; filesystem-safe
  playlist names; command line assembled with the secret but never logged.
- `RpcServer.emit` under concurrent notifications.
- Install: hash mismatch deletes the file; Intel/no-asset falls back to PATH.
- Manual on a real Mac: one playlist end to end; cancel mid-download;
  delete a downloaded file and see it offered again.

## Left to the builder

- Parsing spotDL's progress output, or relying on exit code plus
  file-presence checks.
- Panel layout and copy, following existing panel components.
