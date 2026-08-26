<img src="brand/logo.png" alt="rbsync" width="480">

# rbsync — Spotify playlists into rekordbox

DJing from Spotify needs internet. This takes the playlists you curate there and
rebuilds them inside rekordbox, filled with the tracks you already own locally,
so you can play the same sets offline.

It writes directly to rekordbox's `master.db`. It does not use XML export.

- Pick which playlists to sync — nothing happens without you choosing.
- Every Spotify track is matched against your rekordbox collection.
- Playlists are created in rekordbox under a `Spotify` folder.
- You get a coverage figure per playlist, and a wantlist of what you are missing.

---

## Install

Grab the latest build from [Releases](../../releases).

**macOS** — download the `.dmg` (`aarch64` for Apple Silicon, `x86_64` for
Intel), drag rbsync to Applications, then clear the quarantine flag once:

```bash
xattr -dr com.apple.quarantine /Applications/rbsync.app
```

macOS says an unsigned app "is damaged and can't be opened". It is not damaged —
that is simply what macOS reports when there is no Apple Developer signature.

**Windows** — download the `-setup.exe` and run it. SmartScreen will warn for
the same reason; choose **More info → Run anyway**.

From a checkout, `./install.sh` builds nothing but copies a locally built app to
Applications and clears quarantine for you.

## Updates

The app checks for a new release on launch and offers it in a banner. Nothing is
downloaded until you press **update now**, and it only restarts when you say so.

Every update is signature-verified against a key built into the app. An
auto-updater is a remote code execution channel into every install, so an
artifact that cannot be signed is skipped rather than published — a release with
no valid signature simply offers no update.

The signing key lives in repository secrets and is never committed. For local
builds it is read from `~/.rbsync/updater.key`; `scripts/build-app.sh` picks it
up and tells you how to generate one if it is missing.

## First run: connect Spotify

Spotify requires every application to be registered, so its login page knows
which app is asking. You create a free one — about three minutes, once. The app
walks you through it on first launch, and
[docs/SPOTIFY_SETUP.md](docs/SPOTIFY_SETUP.md) has the same steps with
troubleshooting.

The short version:

1. Create an app at <https://developer.spotify.com/dashboard>.
2. Add exactly `http://127.0.0.1:8888/callback` as a Redirect URI and press Add.
   Use `127.0.0.1`; Spotify rejects `localhost`.
3. Tick **Web API**, save.
4. Copy the **Client ID** into rbsync and press Save.

**Nothing is baked into the released builds.** A Client ID identifies the app,
not you, and is not a secret — but bundling one would put a single person's
Spotify quota behind everyone's usage, and Development Mode allows only five
users per app. Your own app has its own quota.

Ignore the **Client secret** entirely. This app uses PKCE and never needs it.

### Sharing with other people

A Spotify app in Development Mode allows **5 authenticated users**, added by hand
in the dashboard under *Users Management*, and the app owner needs Premium.
Extended Quota Mode lifts that, but Spotify grants it only to registered
organizations with 250,000+ monthly active users. So: either add up to four
people to your app, or have each of them make their own.

## Syncing

1. **Quit rekordbox.** The app refuses to write while it is running.
2. Open rbsync and press **Sync…** (bottom left). That opens a separate window:
   your Spotify playlists on the left, your whole rekordbox playlist tree on the
   right, folders and all.
3. Tick the playlists you want. Nothing is selected by default.
4. **Import into rekordbox.** It matches every track and writes the results in
   one action, then reports exactly what landed and where the backup went.
5. Open rekordbox and look in the `Spotify` folder.

Your selection persists, so a repeat sync is: open, Import.

The left column breaks each playlist down as **matched · review · missing** over
the Spotify total, so `5 · 1 · 5 / 11` means five found, one waiting on your
decision, five you do not own. Review decisions live in the **Tracks** view and
are remembered, so a track is only ever asked about once.

## Safety

Writing to a rekordbox library is the riskiest thing here, so the app refuses
rather than gambles:

- **Rekordbox must be closed.** Two processes writing that database corrupts it.
- **A verified backup is taken before every write**, and the byte count is
  checked before anything changes.
- **Nothing is written until you press Apply** on a plan you have seen.
- **One transaction per Apply** — it all lands, or none of it does.
- **Removals are opt-in.** By default a sync only adds, so tracks you added by
  hand in rekordbox are never destroyed.

### Cloud Library Sync

If you use rekordbox **Cloud Library Sync**, turn it off before syncing.
Pioneer's cloud sync can revert or duplicate playlists written by third-party
tools. The app warns about this but cannot detect it for you.

## Backups and going back

**Backups** in the toolbar lists every backup, takes one on demand, reveals one
in your file manager, and restores one.

Two things make restoring trustworthy:

- **The baseline is kept forever.** A copy from before rbsync ever wrote to your
  library is taken once and never pruned — the rolling backups are all
  post-rbsync after ten syncs, so without it there would be nothing original to
  return to.
- **The write-ahead log travels with it.** rekordbox runs SQLite in WAL mode, so
  recent commits live in `master.db-wal`, not `master.db`. Backing up only the
  main file captures a stale database, and restoring only the main file leaves
  the newer WAL to replay straight back over it. All three files move as one set.

Restoring copies the current state aside first, so a restore is itself
reversible, and it refuses to run while rekordbox is open.

## Matching

Three bands, both thresholds adjustable in Settings:

| Band | Meaning | Default |
|---|---|---|
| **matched** | Confident. Added without asking. | score ≥ 0.88 |
| **review** | Plausible, not certain. You decide once, forever. | 0.62 – 0.88 |
| **missing** | No local copy. Goes on the wantlist. | score ≤ 0.62 |

Score combines normalized title similarity (55%), artist overlap (30%) and
duration proximity (15%). Two rules override it:

- **Matching ISRCs accept immediately.**
- **A duration gap over 30 seconds never auto-accepts** — this is what stops a
  radio edit being swapped for an extended mix in a live set. When the names and
  artist match, though, the longer copy is still offered for review rather than
  discarded: owning the extended mix of a track Spotify lists at radio length is
  the normal case for a DJ, and reporting it as "you do not own this" was wrong.

Titles are normalized against what real libraries contain: `(Original Version)`,
`(OFFICIAL SONG)`, `[Prod. By …]`, `feat.` clauses, leading track numbers and
diacritics.

### Duplicates

Collections are full of duplicate rows — one real library measured 82% . When
several copies match, the app prefers the analysed, highest-bitrate copy and
picks the same one every run.

The top-scoring candidate is not always the one you want, so **change** on any
row lists every candidate with its file, length, bitrate and score. Your choice
is remembered and overrides the ranking from then on.

## Will it actually play?

rekordbox stores the path it imported a track from. If the file moved, was
deleted, or lives on a drive you have not plugged in, rekordbox still lists the
track — and it will not play.

Matched tracks are checked against disk, and the two causes are kept apart
because the remedies differ:

| Badge | Meaning | Fix |
|---|---|---|
| **offline** | On a drive that is not connected | Plug the drive in |
| **no file** | The drive is there, the file is not | Re-download or re-import |

**In rekordbox** in the toolbar shows the same for the whole collection: how many
tracks would play right now, and exactly which drives to reconnect. Syncing works
either way — rekordbox stores the path, so tracks light up when the drive
returns.

Every matched row has a **file** button that reveals the track in Finder or
Explorer.

## Coverage and the wantlist

Per playlist: `matched / total` as a percentage, plus counts per band.

The wantlist is **global, not per playlist** — one list across every playlist in
the plan, deduplicated so a track missing from three playlists is something you
buy once. The `playlist` column names every playlist that wants it. For a single
playlist's wantlist, select only that playlist.

Exported as CSV and as plain `Artist - Title` lines for pasting into a search
tool, with buttons to copy the list or reveal the file.

## Plans are remembered

Planning fetches every selected playlist and matches it against the whole
collection, so the result is stored locally and restored when you reopen the app.

A stored plan is discarded and recomputed when anything that would change its
outcome changes: the playlist was edited on Spotify, the thresholds or removal
setting changed, you accepted or rejected a match, the collection size changed,
or you applied a sync. Out-of-date plans show greyed with a `*`. **Plan sync**
always recomputes.

## History

Every Apply is recorded — playlist, tracks added and removed, coverage at the
time, and the backup that goes with it. See **History**, or:

```bash
rbsync history --limit 20
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
cd core && uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest
```

Rekordbox tests run against a copy of your real `master.db` and skip when none
is present. They never open the original. Point them elsewhere with
`RBSYNC_TEST_DB=/path/to/master.db`.

### Working on the interface

Rebuilding a native bundle for every CSS change is slow, so the core can serve
the same JSON-RPC API over localhost HTTP; the UI detects it is not inside Tauri
and uses that instead.

```bash
cd core && .venv/bin/python -m rbsync.cli serve
cd ui && npm run dev
```

Add a fake Spotify account — playlists built from your real collection plus
tracks nobody owns — and point the app at a copy of your database, so the whole
flow including Apply can be exercised with nothing at risk:

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

### Building the app

```bash
./scripts/build-app.sh   # freezes the core, then bundles with Tauri
./install.sh             # copies to /Applications and makes it launchable
```

`install.sh` does three things, and all three matter: `ditto` (rather than
`cp -R`, which can drop the metadata a code signature depends on), clears the
macOS quarantine flag, and re-signs ad-hoc. Without a valid signature macOS
reports the app as "damaged" and kills it *and its sidecar* on launch — clearing
quarantine alone does not fix that.

**Requires Rust 1.88 or newer.** Tauri's dependency tree will not compile on
older toolchains.

## Releases

Bump the version in the repo first, then tag it. The workflow also stamps the
version from the tag inside the runner, but that stamp is never committed back —
so without bumping here, local builds keep reporting the old number while
releases climb.

```bash
./scripts/set-version.sh 0.2.0
git commit -am "chore: version 0.2.0"
git tag v0.2.0 && git push origin main v0.2.0
```

The workflow runs the test suite, freezes the Python core, builds macOS (Apple
Silicon and Intel) and Windows bundles, signs the update payloads, generates
`latest.json`, and publishes the lot to a GitHub release. Intel is best-effort — GitHub retired the
`macos-13` runners, so a missing Intel runner never blocks a release — but the
job refuses to publish an empty one.

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
PyInstaller rather than resolving it at runtime. Running via `uvx` would require
every user to install `uv` and be online the first time they launch — for an app
whose whole purpose is working offline, that is the wrong trade. The cost is
about 1.7 seconds of startup while the bundle unpacks, paid once per launch
because the sidecar stays alive for the session.

## Status

Working and used against a real 12,000-track library: playlist selection and
browsing, matching with review and bulk actions, playlist writes, coverage
reporting, wantlist export, file-availability checks, sync history, backups with
restore, playlist-tree repair, and in-app updates on macOS and Windows.

Not built yet: importing new audio files into the rekordbox collection, and
assisted downloading of wantlist tracks.

Untested: the Windows build has been produced and installed by CI but never run
by a person — treat it as unproven until someone opens it.
