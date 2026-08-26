# Spotify → Rekordbox Sync

Recreate your Spotify playlists inside rekordbox, filled with the tracks you
already own locally, and get a list of what you are still missing.

Built for DJing offline: the curation stays in Spotify, the playing happens in
rekordbox without needing internet.

## What it does

- Reads your Spotify playlists (you pick which ones — nothing is synced by default).
- Matches each Spotify track against your rekordbox collection by artist, title,
  duration, and ISRC where available.
- Creates the playlists in rekordbox under a `Spotify` folder, containing the
  local files it matched.
- Shows per-playlist coverage — what percentage of the playlist you actually own.
- Exports a wantlist of the tracks you are missing, so you know what to go buy —
  as CSV, and as plain `Artist - Title` lines you can paste into Soulseek.
- Keeps a history of every write, with the backup that goes with it.

It writes directly to rekordbox's `master.db`. It does not use XML export.

## Safety

Writing to a rekordbox library is the risky part, so the app is built to refuse
rather than gamble:

- **Rekordbox must be closed.** The app detects a running rekordbox and refuses
  to write. Two processes writing that database corrupts it.
- **Every write is preceded by a verified backup**, kept in
  `~/Library/Application Support/rbsync/backups/` (last 10).
- **Nothing is written until you press Apply** on a preview that tells you
  exactly how many tracks will be added and removed.
- **All changes for one Apply commit as a single transaction**, or roll back
  entirely.
- **Removals are opt-in.** By default the sync only adds, so tracks you added
  manually in rekordbox are never destroyed.

### Cloud Library Sync

If you use rekordbox **Cloud Library Sync**, turn it off before syncing.
Pioneer's cloud sync can revert or duplicate playlists written by third-party
tools. The app shows a warning about this but cannot detect it for you.

## Setup

### 1. Sign in to Spotify

Press **Sign in with Spotify**. That is the whole setup — the app ships its own
Spotify Client ID and uses PKCE, so there is no secret to paste and nothing to
configure.

A Client ID is public information under PKCE (it appears in the authorize URL of
every desktop and mobile app), which is why it can safely be bundled.

If you would rather use your own Spotify app, put its Client ID in
**Settings → Spotify** with `http://127.0.0.1:8888/callback` as a redirect URI.
A Client ID you set always overrides the bundled one.

#### The hard limit on sharing this with friends

Spotify caps a Development Mode app at **5 authenticated users**, and each of
them has to be added by email in the app owner's Developer Dashboard under
*Users Management*. The app owner also needs Spotify Premium.

Extended Quota Mode removes the cap, but as of 2026 Spotify only grants it to
registered organizations with a launched service and **250,000+ monthly active
users**. That is not attainable for a tool like this.

So realistically: you plus four friends on the bundled app. Beyond that, each
additional person must create their own free Spotify app (three minutes) and
paste their own Client ID into Settings — that path has no user limit.

### 2. Sync

1. Quit rekordbox.
2. Open the app. Your playlists appear on the left, none selected.
3. Check the playlists you want. Press **Plan sync**.
4. Review anything in the amber band — use shift-click and the bulk
   Accept/Reject buttons. Your decisions are remembered permanently.
5. Press **Apply to rekordbox**.
6. Open rekordbox. The playlists are in the `Spotify` folder.

## Matching

Three bands, both thresholds adjustable in Settings:

| Band | Meaning | Default |
|---|---|---|
| **matched** | Confident. Added without asking. | score ≥ 0.88 |
| **review** | Plausible but not certain. You decide once, forever. | 0.62 – 0.88 |
| **missing** | No local copy. Goes to the wantlist. | score ≤ 0.62 |

Score combines normalized title similarity (55%), artist overlap (30%), and
duration proximity (15%). Two rules override it:

- **Matching ISRCs accept immediately.**
- **A duration gap over 30 seconds rejects outright** — this is what stops a
  radio edit being swapped for an extended mix in a live set.

Titles are normalized against the noise real libraries contain:
`(Original Version)`, `(OFFICIAL SONG)`, `[Prod. By ...]`, `feat.` clauses,
leading track numbers, and diacritics.

When several copies of the same track exist in your collection, the app prefers
the analysed, highest-bitrate copy, and picks the same one every run.

### Choosing a different copy

The top-scoring candidate is not always the one you want — 82% of a real
collection turns out to be duplicate rows, and remixes score close to their
originals. **change** on any row opens every candidate the matcher considered,
with its file, length, bitrate and score, and lets you pick one. That choice is
remembered and overrides the ranking on every future sync.

## History and backups

Every Apply is recorded: which playlist, how many tracks added and removed,
the coverage at the time, and the path of the backup taken immediately before.
See it under **History** in the app, or:

```bash
rbsync history --limit 20
```

To roll back, quit rekordbox and copy the backup over `master.db`:

```bash
cp ~/Library/Application\ Support/rbsync/backups/master_<timestamp>.db \
   ~/Library/Pioneer/rekordbox/master.db
```

## Command line

The Python core works on its own:

```bash
rbsync status
rbsync playlists
rbsync select <playlist-id> <playlist-id>
rbsync plan
rbsync apply --yes
rbsync history
rbsync wantlist --out ~/Desktop/wantlist.csv
rbsync wantlist --format txt --out ~/Desktop/wantlist.txt
```

`apply` refuses to run without `--yes`.

## Development

```bash
cd core && uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -e ".[dev]"
cd core && .venv/bin/python -m pytest
```

Rekordbox tests run against a copy of your real `master.db` and skip when none
is present. They never open the original. Point them elsewhere with
`RBSYNC_TEST_DB=/path/to/master.db`.

### Working on the interface

Rebuilding a native bundle for every CSS change is slow, so the core can serve
the same JSON-RPC API over localhost HTTP. The UI detects that it is not running
inside Tauri and talks to the bridge instead.

```bash
cd core && .venv/bin/python -m rbsync.cli serve
cd ui && npm run dev
```

Add a fake Spotify account — playlists built from your real collection, plus
tracks nobody owns — and point the app at a copy of your database, so you can
exercise the whole flow including Apply without any risk:

```bash
cp ~/Library/Pioneer/rekordbox/master.db /tmp/demo_master.db
RBSYNC_HOME=/tmp/rbsync-demo \
RBSYNC_DB_PATH=/tmp/demo_master.db \
RBSYNC_FAKE_SPOTIFY=1 \
  core/.venv/bin/python -m rbsync.cli serve
```

The bridge binds to 127.0.0.1 only and is never started by the packaged app, but
anything that can reach it can write to the configured rekordbox database — do
not leave it running.

To build the desktop app:

```bash
./core/build_sidecar.sh
cd ui && npm install && npm run tauri build
```

**Requires Rust 1.88 or newer.** Tauri's dependency tree (`icu_properties`,
`plist`, `time`) will not compile on older toolchains. Homebrew's `rust`
formula may lag; `rustup` is the reliable way to stay current.

## Architecture

```
Tauri v2 shell (Rust)  — window, OAuth loopback listener, sidecar lifecycle
  └── React + TypeScript UI  — never touches the database
      └── JSON-RPC 2.0 over stdio
          └── Python core (PyInstaller binary)
              └── pyrekordbox → master.db
```

pyrekordbox handles SQLCipher unlocking and rekordbox's update-sequence
bookkeeping, which is why the core is Python rather than Rust.

### Why a frozen binary instead of uv/uvx

`uv` is used for development, but the shipped app freezes the core with
PyInstaller instead of resolving it at runtime. Running the core via `uvx` would
require every user to install `uv` first and to be online the first time they
launch — for an app whose entire purpose is working offline, that is the wrong
trade. The frozen binary is self-contained and needs neither.

The cost is about 1.7 seconds of startup while the bundle unpacks. That is paid
once when the app launches, because the sidecar process stays alive for the whole
session, not per request.

## Sharing the build with friends

The produced `.dmg` is **unsigned and un-notarized**. macOS will refuse to open
it with "rbsync is damaged and can't be opened" — that message is about the
missing signature, not a corrupt file. Until the app is signed with an Apple
Developer ID and notarized, whoever installs it has to clear the quarantine
attribute once:

```bash
xattr -dr com.apple.quarantine /Applications/rbsync.app
```

Proper signing needs a paid Apple Developer account. Everything else about the
build already works.

## Status

Working: playlist selection, matching, review with bulk actions, playlist
writes, coverage reporting, wantlist export.

Not yet built: importing new audio files into the rekordbox collection, and
assisted downloading of wantlist tracks.
