import { useEffect, useMemo, useState } from "react";
import { rpc } from "../rpc";
import { Spinner } from "./Spinner";

export interface DecisionRow {
  spotifyId: string;
  contentId: string;
  accepted: boolean;
  decidedAt: string;
  trackDisplay: string;
  contentDisplay: string;
  playlistName: string;
}

interface Props {
  onClose: () => void;
  /** Called after decisions were undone, so plans can be recomputed. */
  onChanged: () => void;
}

type Filter = "all" | "accepted" | "rejected";

/**
 * Every accept and reject you made, and a way to take one back.
 *
 * A decision silently overrides matching for that track in every playlist. A
 * rejection made by accident hides a track you own, so decisions have to be
 * visible and undoable, not just stored.
 */
export function DecisionsPanel({ onClose, onChanged }: Props) {
  const [rows, setRows] = useState<DecisionRow[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    rpc
      .call<{ decisions: DecisionRow[] }>("decisions.list")
      .then((result) => setRows(result.decisions))
      .catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));

  useEffect(() => {
    void load();
  }, []);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (rows ?? []).filter((row) => {
      if (filter === "accepted" && !row.accepted) return false;
      if (filter === "rejected" && row.accepted) return false;
      if (!needle) return true;
      return [row.trackDisplay, row.contentDisplay, row.playlistName]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [rows, filter, query]);

  const undo = async (ids: string[]) => {
    setBusy(true);
    setError(null);
    try {
      await rpc.call("decisions.forget", { spotifyIds: ids });
      await load();
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const rejectedCount = (rows ?? []).filter((row) => !row.accepted).length;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal decisions-modal" onClick={(event) => event.stopPropagation()}>
        <h2>Decisions</h2>
        <p className="hint">
          Matches you accepted or rejected by hand. A decision applies to that Spotify track in
          every playlist and replaces automatic matching. <strong>Rejected</strong> means "not this
          file": other copies are still offered for review. <strong>Undo</strong> lets the track be
          matched afresh the next time you plan.
        </p>

        {error && <div className="banner error">{error}</div>}

        <div className="decisions-toolbar">
          <div className="filters">
            {(["all", "accepted", "rejected"] as Filter[]).map((value) => (
              <button
                key={value}
                className={filter === value ? "tab active" : "tab"}
                onClick={() => setFilter(value)}
              >
                {value}
              </button>
            ))}
          </div>
          <input
            className="search"
            placeholder="Filter by track, file or playlist"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        <div className="table-wrap decisions-table">
          {rows === null ? (
            <Spinner size={13} label="Loading decisions…" />
          ) : (
            <table>
              <thead>
                <tr>
                  <th className="col-band">decision</th>
                  <th>Spotify track</th>
                  <th>rekordbox file</th>
                  <th>playlist</th>
                  <th>when</th>
                  <th className="col-change"></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => (
                  <tr key={row.spotifyId}>
                    <td className="col-band">
                      <span className={`band ${row.accepted ? "accept" : "reject"}`}>
                        {row.accepted ? "accepted" : "rejected"}
                      </span>
                    </td>
                    <td title={row.trackDisplay || row.spotifyId}>
                      {row.trackDisplay || <span className="muted">unknown track · {row.spotifyId}</span>}
                    </td>
                    <td title={row.contentDisplay}>
                      {row.contentId ? (
                        row.contentDisplay || <span className="muted">file {row.contentId}</span>
                      ) : (
                        <span className="muted">none of the files</span>
                      )}
                    </td>
                    <td className="muted">{row.playlistName || "—"}</td>
                    <td className="muted">{formatWhen(row.decidedAt)}</td>
                    <td className="col-change">
                      <button className="chip" disabled={busy} onClick={() => void undo([row.spotifyId])}>
                        undo
                      </button>
                    </td>
                  </tr>
                ))}
                {shown.length === 0 && (
                  <tr>
                    <td colSpan={6} className="empty">
                      {rows.length === 0 ? "No decisions yet." : "Nothing matches."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        <div className="modal-actions">
          {rejectedCount > 0 && (
            <button className="link" disabled={busy} onClick={() => void undo((rows ?? []).filter((r) => !r.accepted).map((r) => r.spotifyId))}>
              undo all {rejectedCount} rejections
            </button>
          )}
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}
