import { useMemo } from "react";
import type { Band, PlaylistPlan, TrackPlan } from "../types";

export type BandFilter = "all" | Band;

interface Props {
  plan: PlaylistPlan | null;
  filter: BandFilter;
  onFilter: (value: BandFilter) => void;
  selectedIds: Set<string>;
  onSelect: (ids: Set<string>) => void;
  onDecide: (tracks: TrackPlan[], accepted: boolean) => void;
  lastClicked: string | null;
  onLastClicked: (id: string | null) => void;
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
  lastClicked,
  onLastClicked,
}: Props) {
  const rows = useMemo(() => {
    if (!plan) return [];
    return filter === "all" ? plan.tracks : plan.tracks.filter((t) => t.band === filter);
  }, [plan, filter]);

  if (!plan) {
    return (
      <section className="tracks empty-state">
        <p>Select playlists on the left, then press Plan sync.</p>
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
                  <td className="col-local" title={best?.folderPath ?? ""}>
                    {best ? best.display : <span className="muted">no local match</span>}
                  </td>
                  <td className="col-score">{row.score ? row.score.toFixed(2) : "—"}</td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="empty">
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
