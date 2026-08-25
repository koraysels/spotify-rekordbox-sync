# Spotify → Rekordbox Playlist Sync — Design

Date: 2026-08-25
Status: Approved (brainstorming complete)

## Problem

DJing from Spotify requires internet. The user has many curated Spotify
playlists and a 12,630-track local rekordbox collection. They want those
playlists recreated in rekordbox, populated with the local tracks they already
own, and a clear report of what is missing so they can go buy or download it.

## Goals

1. Recreate selected Spotify playlists inside rekordbox's `master.db`.
2. Match Spotify tracks against the existing rekordbox collection.
3. Report per-playlist coverage (% matched) and export a wantlist of unmatched
   tracks.
4. Ship as a distributable desktop app friends can install.

## Non-Goals (v1)

- Importing new audio files into the rekordbox collection (phase 2).
- Automatic downloading via Soulseek/Bandcamp (phase 3).
- Rekordbox XML export. Explicitly rejected: master.db only.
- Audio fingerprinting against Spotify (impossible — no audio access).

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Tauri v2 shell, React+TS UI, Python sidecar | Small distributable, low RAM, TS UI, pyrekordbox for DB |
| D2 | pyrekordbox for all master.db access | Owns SQLCipher unlock + USN bookkeeping; reimplementing is weeks of risk |
| D3 | Spotify auth: per-user Client ID default, shared dev-app allowlist supported | Avoids the 25-user dev cap; no secret shippable in a desktop app |
| D4 | Match against existing collection only | Playlist writes and content imports are different risk classes |
| D5 | Three-band matching: auto-accept / review / reject, two tunable thresholds | Avoids silently pairing a radio edit with an extended mix |
| D6 | Additive sync; removals opt-in per sync via preview | Never destroys manual rekordbox edits |
| D7 | Explicit playlist selection; no default sync-all | User has many playlists; blanket sync is a footgun |
| D8 | Persistent decision cache | Each ambiguous track is reviewed once, ever |

## Verified Feasibility (spike, 2026-08-25)

Run against a copy of the user's real `master.db` (86MB, rekordbox 7):

- `Rekordbox6Database(path, unlock=True)` unlocks with no manual key extraction.
- Read: 12,630 content rows, 57 playlists.
- Write API present: `create_playlist`, `create_playlist_folder`,
  `add_to_playlist`, `remove_from_playlist`, `delete_playlist`.
- Metadata coverage measured: **Title 100%, Length 100%, Artist 91%, ISRC 4.2%**.

Consequence: ISRC is an exact-match fast path for a small minority. Normalized
artist+title similarity, discriminated by duration, is the backbone.

## Architecture

```
Tauri v2 shell (Rust — thin glue)
├── WebView: React + TypeScript UI          (all UI; never touches master.db)
├── Rust: sidecar lifecycle, OAuth loopback server, OS keychain
└── JSON-RPC 2.0 over stdio
    └── Python sidecar (PyInstaller onefile)
        ├── spotify.py    OAuth PKCE, playlist + track fetch, paging
        ├── matcher.py    normalization, scoring, banding
        ├── rekordbox.py  pyrekordbox access, safety gate, writes
        ├── cache.py      SQLite: decisions, selection, sync history
        └── rpc.py        dispatch, progress notifications
```

Language boundaries are strict: Rust owns OS-facing concerns, Python owns
rekordbox-facing concerns, TypeScript owns presentation.

### Local state — `~/Library/Application Support/rbsync/`

- `cache.db` — match decisions, playlist selection, sync history, Spotify snapshots
- `backups/master_<ISO8601>.db` — pre-write copies, last 10 retained
- Spotify tokens — OS keychain via Rust, never in `cache.db`

## Safety Model

Writing to `master.db` is the highest-risk operation in this system. Before any
write, `rekordbox.py` enforces, in order:

1. **Rekordbox not running.** Process detection; refuse with a clear message
   if found. Concurrent access corrupts the database.
2. **Backup taken.** Copy `master.db` to `backups/`, verify byte count matches
   before proceeding.
3. **Single transaction per Apply.** All playlist mutations commit together.
4. **Rollback on any exception**, with the restore path shown to the user.
5. **Cloud Library Sync warning.** A one-time banner: third-party writes can be
   reverted or duplicated when Pioneer's cloud sync is enabled. No automatic
   detection in v1.

Nothing is written until the user presses Apply on a preview.

## Matching Pipeline

Input: Spotify track (name, artists[], album, duration_ms, ISRC).
Candidates: rekordbox `DjmdContent` rows.

### Normalization

Applied to both sides before comparison:

- Lowercase, Unicode NFKD, strip diacritics and punctuation, collapse whitespace.
- Strip noise tokens observed in the real library: `(original version)`,
  `(official song)`, `(official video)`, `[prod. by X]`, `(prod X)`, `feat.`/`ft.`
  and everything after it, bare track-number prefixes (`03 `).
- Featured artists are extracted rather than discarded: they move into a
  secondary artist set, because rekordbox stores them inconsistently — sometimes
  in the title, sometimes in the artist field (`Wiz Khalifa Ft. Travis Scott`).
- Artist field split on `&`, `,`, `ft`, `feat`, `x`, `vs` into an artist set.

### Scoring

Score in [0,1], computed as a weighted sum:

- Title similarity (token-set ratio) — weight 0.55
- Artist set overlap (best-pair similarity) — weight 0.30
- Duration proximity — weight 0.15; full credit within ±2s, decaying to zero at ±15s

Hard rules that override the score:

- **ISRC equality → immediate accept** (score forced to 1.0). Rare but free.
- **Duration delta > 30s → reject**, regardless of title/artist. This is the
  guard against pairing a radio edit with an extended mix.
- Mix-descriptor mismatch (`remix`, `extended`, `radio edit`, `live`, `dub`)
  between the two sides caps the score below the auto-accept band.

### Banding

- `score >= auto_accept` (default 0.88) → accept without asking
- `reject < score < auto_accept` (default 0.62) → review queue
- `score <= reject` → unmatched, goes to the wantlist

Both thresholds are user-settable. Every decision — accept or reject — is
written to the decision cache keyed by (spotify_track_id, rekordbox_content_id),
so a reviewed track is never asked about again.

### Indexing

12,630 tracks × hundreds of Spotify tracks is too many pairs for brute force.
Candidates are pre-filtered by a token inverted index over normalized titles,
plus a duration bucket (±30s), before any expensive similarity is computed.

## Sync Flow

1. User checks playlists (none checked by default). Selection persists.
2. **Sync selected (N)** — disabled at 0.
3. Fetch playlist tracks from Spotify.
4. Match each track; apply cached decisions first.
5. If the review band is non-empty, present it — with bulk accept/reject on
   multi-select, never one-at-a-time-only.
6. Preview: `+12 add, −3 remove, 8 unmatched` per playlist.
7. Apply → safety gate → backup → transaction → commit.
8. Coverage report + wantlist export.

Playlists are created under a `Spotify` folder in the rekordbox playlist tree,
one playlist per Spotify playlist, name mirrored.

## UI

Master-detail, single window, dense — deliberately closer to a CLI than a wizard.

- **Left:** playlist list, checkbox each, coverage % badge, last-synced time.
- **Right:** track table for the selected playlist. One row per Spotify track:
  state (green matched / amber review / red missing), Spotify artist–title,
  matched rekordbox file, score.
- **Bulk actions:** shift-click range select, select-all-in-band, bulk
  accept/reject/unlink. Automation applies here, not to playlist choice.
- **Bottom bar:** Sync selected (N), coverage summary, Export wantlist.
- Review and wantlist are filters over this one table, not separate screens.

## Coverage & Wantlist

Per playlist: `matched / total` as a percentage, plus counts per band.
Wantlist export contains every unmatched track: artist, title, album, duration,
ISRC, Spotify URL. Formats: CSV and plain text (copy-paste into Soulseek).

## Testing

- Matcher is pure and gets the heaviest coverage: a fixture set built from real
  library rows, including the messy cases found in the spike.
- Rekordbox writes are tested against a **copy** of a real master.db, never the
  original, asserting playlist and song-playlist rows after commit.
- Safety gate tested: refuses when rekordbox is running, refuses when backup
  fails, rolls back on mid-transaction failure.
- Spotify client tested against recorded fixtures; no live API in tests.

## Phases

- **Phase 1 (this spec):** selection, matching, review, playlist writes,
  coverage, wantlist export.
- **Phase 2:** scan folders on disk, import matched-but-uncollected files into
  the rekordbox collection.
- **Phase 3:** assisted acquisition of wantlist tracks.
