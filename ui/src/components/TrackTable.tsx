import { useMemo, useState } from "react";
import { copyText, searchQueryFor } from "../clipboard";
import type { Band, PlaylistPlan, SpotifyTrack, TrackPlan } from "../types";

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
}

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
}: Props) {
  const blocked = plan?.error ?? null;

  const rows = useMemo(() => {
    if (!plan) return [];
    return filter === "all" ? plan.tracks : plan.tracks.filter((t) => t.band === filter);
  }, [plan, filter]);

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
              <span className="muted">Press Plan sync to match these against rekordbox.</span>
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
        <p>Select a playlist to see what's in it, then press Plan sync.</p>
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
        <table>
          <thead>
            <tr>
              <th className="col-check"></th>
              <th className="col-band">state</th>
              <th>Spotify</th>
              <th>Rekordbox match</th>
              <th className="col-score">score</th>
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
                >
                  <td className="col-check">
                    <input type="checkbox" readOnly checked={selectedIds.has(row.track.id)} />
                  </td>
                  <td className="col-band">
                    <span className={`band ${row.band}`}>{BAND_LABEL[row.band]}</span>
                  </td>
                  <td className="col-spotify" title={row.track.display}>
                    {row.track.display}
                  </td>
                  <td className="col-local" title={row.band === "reject" ? "" : best?.folderPath ?? ""}>
                    {row.band === "reject" || !best ? (
                      // A rejected row's best candidate scored too low to use.
                      // Showing it here reads as "this is your match", which it
                      // is not, so the row states plainly that nothing matched.
                      <span className="muted">no local match</span>
                    ) : (
                      best.display
                    )}
                  </td>
                  <td className="col-score">{row.score ? row.score.toFixed(2) : "—"}</td>
                  <td className="col-change">
                    {row.band === "reject" ? (
                      <CopyActions track={row.track} />
                    ) : (
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
                    )}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  Nothing in this band.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
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
