import { Spinner } from "./Spinner";
import type { ApplyResult } from "../types";

export interface ApplyState {
  phase: "running" | "done" | "error";
  message: string;
  results: ApplyResult[];
  error: string | null;
}

interface Props {
  state: ApplyState;
  onClose: () => void;
  onReveal: (path: string) => void;
}

/**
 * What happens when you press Apply.
 *
 * Writing to rekordbox is the one irreversible step, so it gets its own
 * foreground dialog rather than a line in the status bar: it reports progress
 * while it runs, and afterwards states exactly what was written and where the
 * backup went, so the result is never something you have to go looking for.
 */
export function ApplyDialog({ state, onClose, onReveal }: Props) {
  const added = state.results.reduce((sum, entry) => sum + entry.added, 0);
  const removed = state.results.reduce((sum, entry) => sum + entry.removed, 0);
  const backup = state.results[0]?.backupPath ?? "";

  return (
    <div className="modal-backdrop">
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        {state.phase === "running" && (
          <>
            <h2>Writing to rekordbox</h2>
            <div className="apply-running">
              <Spinner size={18} />
              <p className="hint">{state.message || "Working…"}</p>
            </div>
            <p className="hint">
              Your library is backed up first, and everything is written in a single
              transaction. Leave rekordbox closed until this finishes.
            </p>
          </>
        )}

        {state.phase === "done" && (
          <>
            <h2>Done</h2>
            <div className="health">
              <div className="health-row">
                <span>Tracks added</span>
                <span className="num">{added}</span>
              </div>
              {removed > 0 && (
                <div className="health-row">
                  <span>Tracks removed</span>
                  <span className="num">{removed}</span>
                </div>
              )}
              <div className="health-row">
                <span>Playlists written</span>
                <span className="num">{state.results.length}</span>
              </div>
              {added === 0 && state.results.length > 0 && (
                <p className="hint">
                  Nothing new to add — rekordbox already had every matched track from
                  these playlists.
                </p>
              )}
            </div>

            {state.results.length > 0 && (
              <div className="table-wrap history">
                <table>
                  <thead>
                    <tr>
                      <th>playlist</th>
                      <th className="num">added</th>
                      <th className="num">removed</th>
                      <th className="num">in rekordbox</th>
                      <th className="num">missing</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.results.map((entry) => (
                      <tr key={entry.playlistId}>
                        <td title={entry.playlistName}>{entry.playlistName}</td>
                        <td className="num">{entry.added || "—"}</td>
                        <td className="num">{entry.removed || "—"}</td>
                        <td className="num">
                          <span className="count ok">{entry.matched}</span>
                          <span className="count total"> / {entry.total}</span>
                        </td>
                        <td className="num">
                          {entry.missing ? (
                            <span className="count bad" title="tracks you do not own — on the wantlist">
                              {entry.missing}
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <p className="hint">
              Open rekordbox and look in the <code>Spotify</code> folder.
              {backup && (
                <>
                  {" "}
                  A backup of your library was saved first.
                </>
              )}
            </p>

            <div className="modal-actions">
              {backup && (
                <button className="ghost" onClick={() => onReveal(backup)}>
                  Show backup
                </button>
              )}
              <button className="primary" onClick={onClose}>
                Close
              </button>
            </div>
          </>
        )}

        {state.phase === "error" && (
          <>
            <h2>The sync did not finish</h2>
            <p className="hint warn">{state.error}</p>
            <p className="hint">
              Each playlist is written in a single transaction, so no playlist is left
              half-written. But if the failure happened partway through, earlier playlists
              may already have landed — open <strong>In rekordbox</strong> to see what is
              actually there, and <strong>Backups</strong> to go back if you want to.
            </p>
            <div className="modal-actions">
              <button className="primary" onClick={onClose}>
                Close
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
