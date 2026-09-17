import { useMemo, useState } from "react";
import { openUrl, revealItemInDir } from "@tauri-apps/plugin-opener";

import { ContextMenu, type MenuItem } from "./ContextMenu";
import { TrackInfoPanel } from "./TrackInfoPanel";

import { copyText, searchQueryFor } from "../clipboard";
import { isTauri } from "../rpc";
import type { Band, PlaylistPlan, SpotifyTrack, TrackFeatures, TrackPlan } from "../types";

export interface FileStatus {
  exists: boolean;
  status: "ok" | "missing" | "offline" | "unknown";
  path: string;
  volume: string;
}

export interface BrowseState {
  tracks: SpotifyTrack[];
  error: string | null;
  loading: boolean;
}

export type BandFilter = "all" | Band;

interface Props {
  plan: PlaylistPlan | null;
  filter: BandFilter;
  onFilter: (value: BandFilter) => void;
  selectedIds: Set<string>;
  onSelect: (ids: Set<string>) => void;
  onDecide: (tracks: TrackPlan[], accepted: boolean) => void;
  onInspect: (row: TrackPlan) => void;
  lastClicked: string | null;
  onLastClicked: (id: string | null) => void;
  /** Contents of the highlighted playlist when no plan has been made yet. */
  browse: BrowseState | null;
  /** Per content id: whether the matched audio file is reachable right now. */
  files: Map<string, FileStatus>;
  /** Audio features per Spotify track id. */
  features: Map<string, TrackFeatures>;
  /** Take back an earlier accept or reject for this row's track. */
  onUndoDecision: (row: TrackPlan) => void;
}

type SortKey = "none" | "energy" | "dance" | "mood" | "bpm";

// Column hints. These say where a number comes from, because none of them are
// yours: they are measurements, not ratings you gave.
const STATE_TIP =
  "matched: confidently found in your collection. review: a likely match worth checking. " +
  "missing: not in your collection. offline / no file: matched, but the audio file is not reachable.";
const SCORE_TIP =
  "How sure rbsync is that the rekordbox file is the same record as the Spotify track, from 0 to 1. " +
  "Computed from title (55%), artist (30%) and length (15%). Not a rating of the track, and not anything you set. " +
  "Above 0.88 is accepted automatically; below 0.62 counts as missing.";
const BPM_TIP =
  "Tempo. From rekordbox's own analysis of the matched file; Spotify's tempo when no file matched.";
const KEY_TIP =
  "Musical key. From rekordbox's analysis of the matched file (your notation, e.g. 8A); " +
  "otherwise derived from Spotify's key and mode, e.g. F#m.";
const ENERGY_TIP =
  "Energy 1–10: how intense and driving the track is. Measured by ReccoBeats from the audio " +
  "(loudness, density, activity), not by you and not by rekordbox. Roughly comparable to a " +
  "Mixed In Key energy, but a different analysis, so the numbers will not match exactly.";
const DANCE_TIP =
  "Danceability 0–100: how steady and rhythmic the track is — tempo stability, beat strength, regularity. " +
  "High means an easy, locked groove; low means loose or free-form.";
const MOOD_TIP =
  "Mood (valence) 0–100: how positive the track sounds. Low is dark, sad or tense; high is bright, happy or euphoric. " +
  "Independent of energy: a track can be fast and dark (high energy, low mood).";

const BAND_LABEL: Record<Band, string> = {
  accept: "matched",
  review: "review",
  reject: "missing",
};

export function TrackTable({
  plan,
  filter,
  onFilter,
  selectedIds,
  onSelect,
  onDecide,
  onInspect,
  lastClicked,
  onLastClicked,
  browse,
  files,
  features,
  onUndoDecision,
}: Props) {
  const blocked = plan?.error ?? null;
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "none", desc: true });
  const [menu, setMenu] = useState<{ x: number; y: number; row: TrackPlan } | null>(null);
  const [info, setInfo] = useState<TrackPlan | null>(null);
  const [widths, setWidths] = useState<Partial<Record<Column, number>>>(loadWidths);

  const resize = (column: Column, width: number) =>
    setWidths((current) => {
      const next = { ...current, [column]: Math.max(MIN_WIDTH, Math.round(width)) };
      saveWidths(next);
      return next;
    });
  const resetWidth = (column: Column) =>
    setWidths((current) => {
      const next = { ...current };
      delete next[column];
      saveWidths(next);
      return next;
    });
  // Once columns are sized by hand, the table may be wider than the window;
  // it scrolls sideways rather than squeezing the other columns to nothing.
  const tableMinWidth = COLUMNS.reduce((sum, column) => sum + (widths[column] ?? DEFAULT_WIDTH[column]), 0);

  const rows = useMemo(() => {
    if (!plan) return [];
    const shown = filter === "all" ? plan.tracks : plan.tracks.filter((t) => t.band === filter);
    if (sort.key === "none") return shown;
    const value = (row: TrackPlan): number => {
      const f = features.get(row.track.id);
      switch (sort.key) {
        case "energy":
          return f?.energy ?? -1;
        case "dance":
          return f?.danceability ?? -1;
        case "mood":
          return f?.valence ?? -1;
        case "bpm":
          return row.candidates[0]?.bpm || f?.tempo || -1;
        default:
          return 0;
      }
    };
    return [...shown].sort((a, b) => (sort.desc ? value(b) - value(a) : value(a) - value(b)));
  }, [plan, filter, sort, features]);

  const sortHeader = (key: SortKey, label: string, tip: string) => (
    <th
      className="col-score sortable"
      title={`${tip}\n\nClick to sort.`}
      onClick={() =>
        setSort((s) => (s.key === key ? (s.desc ? { key, desc: false } : { key: "none", desc: true }) : { key, desc: true }))
      }
    >
      {label}
      {sort.key === key ? (sort.desc ? " ↓" : " ↑") : ""}
      <Resizer column={key as Column} onResize={resize} onReset={resetWidth} />
    </th>
  );

  if (!plan) {
    // Browsing: show what is in the playlist on Spotify, before any matching.
    if (browse) {
      if (browse.loading) {
        return (
          <section className="tracks empty-state">
            <p>Loading playlist…</p>
          </section>
        );
      }
      if (browse.error) {
        return (
          <section className="tracks empty-state">
            <div className="blocked">
              <h3>Spotify won't share this playlist</h3>
              <p>{browse.error}</p>
            </div>
          </section>
        );
      }
      return (
        <section className="tracks">
          <div className="tracks-head">
            <div className="filters">
              <span className="browse-label">
                {browse.tracks.length} track{browse.tracks.length === 1 ? "" : "s"} on Spotify
              </span>
            </div>
            <div className="bulk">
              <span className="muted">Press Find matches to match these against rekordbox.</span>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="col-num">#</th>
                  <th>Spotify</th>
                  <th>album</th>
                  <th className="col-score">length</th>
                </tr>
              </thead>
              <tbody>
                {browse.tracks.map((track, index) => (
                  <tr key={`${track.id}-${index}`}>
                    <td className="col-num">{index + 1}</td>
                    <td title={track.display}>{track.display}</td>
                    <td className="muted" title={track.album}>
                      {track.album}
                    </td>
                    <td className="col-score">{formatMs(track.durationMs)}</td>
                  </tr>
                ))}
                {browse.tracks.length === 0 && (
                  <tr>
                    <td colSpan={4} className="empty">
                      This playlist is empty.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      );
    }

    return (
      <section className="tracks empty-state">
        <p>Select a playlist to see what's in it, then press Find matches.</p>
      </section>
    );
  }

  if (blocked) {
    return (
      <section className="tracks empty-state">
        <div className="blocked">
          <h3>Spotify won't share this playlist</h3>
          <p>{blocked}</p>
          <p className="hint">
            Since February 2026 Spotify only returns the contents of playlists you own or
            collaborate on. To sync this one, open it in Spotify and duplicate it into your
            own account, then sync the copy.
          </p>
        </div>
      </section>
    );
  }

  /** Shift-click extends the selection, which is what makes bulk review usable. */
  const toggleRow = (trackId: string, shiftKey: boolean) => {
    const next = new Set(selectedIds);
    if (shiftKey && lastClicked) {
      const ids = rows.map((r) => r.track.id);
      const from = ids.indexOf(lastClicked);
      const to = ids.indexOf(trackId);
      if (from >= 0 && to >= 0) {
        const [start, end] = from < to ? [from, to] : [to, from];
        for (let i = start; i <= end; i += 1) next.add(ids[i]);
        onSelect(next);
        return;
      }
    }
    if (next.has(trackId)) next.delete(trackId);
    else next.add(trackId);
    onLastClicked(trackId);
    onSelect(next);
  };

  const selectedTracks = rows.filter((row) => selectedIds.has(row.track.id));
  const counts = plan.coverage;

  /** Menu actions for a row, or for the whole selection when the row is part of it. */
  const menuItems = (row: TrackPlan): MenuItem[] => {
    const targets = selectedIds.has(row.track.id) && selectedTracks.length > 1 ? selectedTracks : [row];
    const many = targets.length > 1;
    const count = many ? `${targets.length} tracks` : undefined;
    const best = row.candidates[0];
    const matched = row.band !== "reject" && best;
    const path = files.get(row.contentId ?? "")?.path ?? best?.folderPath ?? "";
    const acceptable = targets.filter((t) => t.candidates.length > 0);

    const items: MenuItem[] = [];
    if (!many) {
      items.push({ label: "Track info…", onSelect: () => setInfo(row) });
      items.push({
        label: row.candidates.length > 0 ? "Choose match…" : "Show candidates…",
        onSelect: () => onInspect(row),
      });
    }
    items.push(
      {
        label: many ? "Accept best matches" : "Accept this match",
        hint: count,
        disabled: acceptable.length === 0,
        onSelect: () => onDecide(acceptable, true),
      },
      {
        label: many ? "Reject these matches" : row.candidates.length > 0 ? "Reject this match" : "Mark as missing",
        hint: count,
        danger: true,
        onSelect: () => onDecide(targets, false),
      },
    );
    const decided = targets.filter((t) => t.reason === "rejected" || t.reason === "cached");
    if (decided.length > 0) {
      items.push({
        label: "Undo decision",
        hint: decided.length > 1 ? `${decided.length} tracks` : undefined,
        onSelect: () => decided.forEach((t) => onUndoDecision(t)),
      });
    }
    items.push({ separator: true });
    if (!many && matched) {
      items.push({
        label: "Show file in Finder",
        disabled: !path || !isTauri(),
        onSelect: () => void revealItemInDir(path).catch(() => {}),
      });
    }
    if (!many) {
      items.push(
        {
          label: `Copy "${searchQueryFor(row.track)}"`,
          disabled: !row.track.name,
          onSelect: () => void copyText(searchQueryFor(row.track)),
        },
        {
          label: "Copy Spotify link",
          disabled: !row.track.url,
          onSelect: () => void copyText(row.track.url),
        },
        {
          label: "Open in Spotify",
          disabled: !row.track.url || !isTauri(),
          onSelect: () => void openUrl(row.track.url).catch(() => {}),
        },
      );
    } else {
      items.push({
        label: "Copy names",
        hint: count,
        onSelect: () => void copyText(targets.map((t) => searchQueryFor(t.track)).join("\n")),
      });
    }
    return items;
  };

  return (
    <section className="tracks">
      <div className="tracks-head">
        <div className="filters">
          <FilterTab value="all" filter={filter} onFilter={onFilter} count={counts.total} label="all" />
          <FilterTab value="accept" filter={filter} onFilter={onFilter} count={counts.matched} label="matched" />
          <FilterTab value="review" filter={filter} onFilter={onFilter} count={counts.review} label="review" />
          <FilterTab value="reject" filter={filter} onFilter={onFilter} count={counts.missing} label="missing" />
        </div>
        <div className="bulk">
          <button className="link" onClick={() => onSelect(new Set(rows.map((r) => r.track.id)))}>
            select shown
          </button>
          <button className="link" onClick={() => onSelect(new Set())}>
            clear
          </button>
          <button
            className="accept"
            disabled={selectedTracks.length === 0}
            onClick={() => onDecide(selectedTracks, true)}
          >
            Accept {selectedTracks.length || ""}
          </button>
          <button
            className="reject"
            disabled={selectedTracks.length === 0}
            onClick={() => onDecide(selectedTracks, false)}
          >
            Reject {selectedTracks.length || ""}
          </button>
        </div>
      </div>

      <div className="table-wrap">
        <table className="resizable" style={{ minWidth: tableMinWidth }}>
          <colgroup>
            {COLUMNS.map((column) => (
              <col key={column} style={widths[column] ? { width: widths[column] } : undefined} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th className="col-check"></th>
              <th className="col-band" title={STATE_TIP}>
                state
                <Resizer column="band" onResize={resize} onReset={resetWidth} />
              </th>
              <th title="The track as Spotify lists it: artist - title.">
                Spotify
                <Resizer column="spotify" onResize={resize} onReset={resetWidth} />
              </th>
              <th title="The file in your rekordbox collection this track was matched to.">
                Rekordbox match
                <Resizer column="local" onResize={resize} onReset={resetWidth} />
              </th>
              {sortHeader("bpm", "bpm", BPM_TIP)}
              <th className="col-score" title={KEY_TIP}>
                key
                <Resizer column="key" onResize={resize} onReset={resetWidth} />
              </th>
              {sortHeader("energy", "energy", ENERGY_TIP)}
              {sortHeader("dance", "dance", DANCE_TIP)}
              {sortHeader("mood", "mood", MOOD_TIP)}
              <th className="col-score" title={SCORE_TIP}>
                match conf.
                <Resizer column="score" onResize={resize} onReset={resetWidth} />
              </th>
              <th className="col-change"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const best = row.candidates[0];
              return (
                <tr
                  key={row.track.id}
                  className={selectedIds.has(row.track.id) ? "row selected" : "row"}
                  onClick={(event) => toggleRow(row.track.id, event.shiftKey)}
                  onDoubleClick={() => setInfo(row)}
                  onContextMenu={(event) => {
                    event.preventDefault();
                    setMenu({ x: event.clientX, y: event.clientY, row });
                  }}
                >
                  <td className="col-check">
                    <input type="checkbox" readOnly checked={selectedIds.has(row.track.id)} />
                  </td>
                  <td className="col-band">
                    <FileAwareBand row={row} file={files.get(row.contentId ?? "")} />
                  </td>
                  <td className="col-spotify" title={`${row.track.display} · ${formatMs(row.track.durationMs)}`}>
                    <span className="cell-text">{row.track.display}</span>
                    <span className="len">{formatMs(row.track.durationMs)}</span>
                  </td>
                  <td className="col-local" title={row.band === "reject" ? "" : best?.folderPath ?? ""}>
                    {row.band === "reject" || !best ? (
                      // A rejected row's best candidate scored too low to use.
                      // Showing it here reads as "this is your match", which it
                      // is not, so the row states plainly that nothing matched.
                      row.reason === "rejected" ? (
                        <span className="muted">you rejected every file for this</span>
                      ) : (
                        <span className="muted">no local match</span>
                      )
                    ) : (
                      <>
                        <span className="cell-text">{best.display}</span>
                        <LengthBadge seconds={best.lengthSeconds} spotifyMs={row.track.durationMs} />
                      </>
                    )}
                    {row.reason === "rejected" && (
                      <button
                        className="chip rejected-chip"
                        onClick={(event) => {
                          event.stopPropagation();
                          onUndoDecision(row);
                        }}
                        data-tip="You rejected a match for this track earlier. Undo to match it afresh."
                      >
                        rejected · undo
                      </button>
                    )}
                  </td>
                  <FeatureCells row={row} features={features.get(row.track.id)} />
                  <td className="col-score">
                    {row.reason === "cached" ? (
                      <span className="muted" title="You chose this match earlier. Not a computed score.">
                        your pick
                      </span>
                    ) : row.score ? (
                      row.score.toFixed(2)
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="col-change">
                    {row.band === "reject" ? (
                      <CopyActions track={row.track} />
                    ) : (
                      <span className="copy-actions">
                        <RevealButton path={files.get(row.contentId ?? "")?.path ?? best?.folderPath ?? ""} />
                        <button
                          className="chip"
                          onClick={(event) => {
                            event.stopPropagation();
                            onInspect(row);
                          }}
                          data-tip="See every candidate and choose one"
                        >
                          change
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={11} className="empty">
                  Nothing in this band.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {menu && (
        <ContextMenu x={menu.x} y={menu.y} items={menuItems(menu.row)} onClose={() => setMenu(null)} />
      )}
      {info && (
        <TrackInfoPanel
          row={info}
          file={files.get(info.contentId ?? info.candidates[0]?.contentId ?? "")}
          features={features.get(info.track.id)}
          onClose={() => setInfo(null)}
          onChooseMatch={() => {
            setInfo(null);
            onInspect(info);
          }}
          onUndoDecision={() => {
            setInfo(null);
            onUndoDecision(info);
          }}
        />
      )}
    </section>
  );
}

/**
 * The band, unless the matched file cannot be played right now.
 *
 * An unplugged drive and a deleted file both mean "won't play", but they have
 * completely different remedies, so they must not look the same.
 */
function FileAwareBand({ row, file }: { row: TrackPlan; file?: FileStatus }) {
  if (file?.status === "offline") {
    const drive = file.volume.replace("/Volumes/", "");
    return (
      <span className="band drive-offline" title={`On ${drive}, which is not connected. Reconnect the drive and this track plays.`}>
        offline
      </span>
    );
  }
  if (file?.status === "missing") {
    return (
      <span className="band missing-file" title={`rekordbox points at ${file.path}, but nothing is there. The file was moved or deleted.`}>
        no file
      </span>
    );
  }
  return <span className={`band ${row.band}`}>{BAND_LABEL[row.band]}</span>;
}

/** Opens the containing folder with the matched file selected. */
function RevealButton({ path }: { path: string }) {
  const [failed, setFailed] = useState(false);

  const reveal = async (event: React.MouseEvent) => {
    event.stopPropagation();
    if (!isTauri() || !path) {
      setFailed(true);
      window.setTimeout(() => setFailed(false), 1800);
      return;
    }
    try {
      await revealItemInDir(path);
    } catch {
      setFailed(true);
      window.setTimeout(() => setFailed(false), 1800);
    }
  };

  return (
    <button
      className={failed ? "chip bad" : "chip"}
      onClick={reveal}
      disabled={!path}
      data-tip={path ? `Show in Finder: ${path}` : "No file path recorded"}
    >
      {failed ? "failed" : "file"}
    </button>
  );
}

function ClipboardIcon() {
  return (
    <svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true" focusable="false">
      <path
        d="M5.5 2.5h5M5.5 2.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v1h-5v-1Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
      <path
        d="M10.5 3.5h1.5a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h1.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true" focusable="false">
      <path
        d="M3.5 8.5l3 3 6-7"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Copy helpers for a track you do not own yet: "Artist - Title" to paste into a
 * shop or search tool, and the Spotify link to open the original.
 */
function CopyActions({ track }: { track: SpotifyTrack }) {
  const [state, setState] = useState<{ what: "link" | "name"; ok: boolean } | null>(null);

  const copy = async (event: React.MouseEvent, what: "link" | "name") => {
    event.stopPropagation();
    const ok = await copyText(what === "link" ? track.url : searchQueryFor(track));
    // Report failure rather than leaving the button looking like it worked.
    setState({ what, ok });
    window.setTimeout(() => setState(null), 1500);
  };

  const done = (what: "link" | "name") => state?.what === what;

  return (
    <span className="copy-actions">
      <button
        className={done("name") ? (state!.ok ? "chip ok" : "chip bad") : "chip"}
        onClick={(event) => copy(event, "name")}
        data-tip={
          done("name")
            ? state!.ok
              ? "Copied to clipboard"
              : "Could not reach the clipboard"
            : `Copy "${searchQueryFor(track)}"`
        }
        disabled={!track.name}
      >
        {done("name") ? <CheckIcon /> : <ClipboardIcon />}
        <span>{done("name") ? (state!.ok ? "copied" : "failed") : "name"}</span>
      </button>
      <button
        className={done("link") ? (state!.ok ? "chip ok" : "chip bad") : "chip"}
        onClick={(event) => copy(event, "link")}
        data-tip={
          !track.url
            ? "No Spotify link for this track"
            : done("link")
              ? state!.ok
                ? "Copied to clipboard"
                : "Could not reach the clipboard"
              : "Copy the Spotify link"
        }
        disabled={!track.url}
      >
        {done("link") ? <CheckIcon /> : <ClipboardIcon />}
        <span>{done("link") ? (state!.ok ? "copied" : "failed") : "link"}</span>
      </button>
    </span>
  );
}

const PITCH = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

/** BPM/key prefer the rekordbox analysis of the matched file; energy etc. come from Spotify's track. */
function FeatureCells({ row, features }: { row: TrackPlan; features?: TrackFeatures }) {
  const local = row.band === "reject" ? undefined : row.candidates[0];
  const bpm = local?.bpm || features?.tempo || 0;
  const key =
    local?.key ||
    (features?.key !== null && features?.key !== undefined && features.key >= 0
      ? `${PITCH[features.key]}${features.mode === 0 ? "m" : ""}`
      : "");
  const pct = (value: number | null | undefined) =>
    value === null || value === undefined ? "—" : String(Math.round(value * 100));
  return (
    <>
      <td className="col-score" title={local?.bpm ? "rekordbox analysis" : bpm ? "Spotify tempo" : ""}>
        {bpm ? bpm.toFixed(0) : "—"}
      </td>
      <td className="col-score">{key || "—"}</td>
      <td className="col-score">
        {features ? (
          <span className={`energy-pill e${features.energyLevel}`} title={`energy ${features.energy.toFixed(2)}`}>
            {features.energyLevel}
          </span>
        ) : (
          <span className="muted">—</span>
        )}
      </td>
      <td className="col-score">{pct(features?.danceability)}</td>
      <td className="col-score">{pct(features?.valence)}</td>
    </>
  );
}

const COLUMNS = ["check", "band", "spotify", "local", "bpm", "key", "energy", "dance", "mood", "score", "change"] as const;
type Column = (typeof COLUMNS)[number];
const WIDTHS_KEY = "rbsync.columnWidths";
const MIN_WIDTH = 36;
/** Used only to work out how wide the table must be; unsized columns still flex. */
const DEFAULT_WIDTH: Record<Column, number> = {
  check: 28, band: 92, spotify: 220, local: 220, bpm: 60, key: 60,
  energy: 60, dance: 60, mood: 60, score: 70, change: 152,
};

function loadWidths(): Partial<Record<Column, number>> {
  try {
    return JSON.parse(localStorage.getItem(WIDTHS_KEY) ?? "{}");
  } catch {
    return {};
  }
}

function saveWidths(widths: Partial<Record<Column, number>>) {
  try {
    localStorage.setItem(WIDTHS_KEY, JSON.stringify(widths));
  } catch {
    // Remembering widths is a convenience; the table works without it.
  }
}

/** Drag handle on a header's right edge. Double-click restores the default width. */
function Resizer({
  column,
  onResize,
  onReset,
}: {
  column: Column;
  onResize: (column: Column, width: number) => void;
  onReset: (column: Column) => void;
}) {
  const start = (event: React.MouseEvent<HTMLSpanElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const header = event.currentTarget.parentElement;
    if (!header) return;
    const startX = event.clientX;
    const startWidth = header.getBoundingClientRect().width;
    const move = (moveEvent: MouseEvent) => onResize(column, startWidth + moveEvent.clientX - startX);
    const stop = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", stop);
      document.body.classList.remove("resizing-column");
    };
    document.body.classList.add("resizing-column");
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);
  };
  return (
    <span
      className="col-resizer"
      onMouseDown={start}
      onClick={(event) => event.stopPropagation()}
      onDoubleClick={(event) => {
        event.stopPropagation();
        onReset(column);
      }}
      title="Drag to resize · double-click to reset"
    />
  );
}

/** Differences below this are encoding and silence, not another version. */
const LENGTH_DIFF_SECONDS = 5;

/**
 * The matched file's length, flagged when it differs from Spotify's.
 *
 * Length is what tells a radio edit from an extended mix, or a 1999 original
 * from a 2008 re-release, when the names are the same.
 */
function LengthBadge({ seconds, spotifyMs }: { seconds: number; spotifyMs: number }) {
  if (!seconds) return null;
  const delta = Math.round(seconds - spotifyMs / 1000);
  const differs = Math.abs(delta) >= LENGTH_DIFF_SECONDS;
  return (
    <span
      className={differs ? "len len-diff" : "len"}
      title={
        differs
          ? `${Math.abs(delta)}s ${delta > 0 ? "longer" : "shorter"} than the Spotify version — possibly a different version`
          : "Same length as the Spotify version"
      }
    >
      {formatMs(seconds * 1000)}
      {differs ? ` (${delta > 0 ? "+" : "−"}${formatMs(Math.abs(delta) * 1000)})` : ""}
    </span>
  );
}

function formatMs(ms: number): string {
  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function FilterTab({
  value,
  filter,
  onFilter,
  count,
  label,
}: {
  value: BandFilter;
  filter: BandFilter;
  onFilter: (value: BandFilter) => void;
  count: number;
  label: string;
}) {
  return (
    <button
      className={filter === value ? "tab active" : "tab"}
      onClick={() => onFilter(value)}
    >
      {label} <span className="tab-count">{count}</span>
    </button>
  );
}
