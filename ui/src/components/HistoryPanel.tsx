import { useEffect, useState } from "react";
import { rpc } from "../rpc";
import type { HistoryEntry } from "../types";

interface Props {
  onClose: () => void;
}

export function HistoryPanel({ onClose }: Props) {
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    rpc
      .call<{ entries: HistoryEntry[] }>("history.list", { limit: 100 })
      .then((result) => setEntries(result.entries))
      .catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, []);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wide" onClick={(event) => event.stopPropagation()}>
        <h2>Sync history</h2>
        <p className="hint">
          Every write to rekordbox, with the backup taken before it. Restore a backup by
          quitting rekordbox and copying the file over <code>master.db</code>.
        </p>

        {error && <p className="hint warn">{error}</p>}
        {!entries && !error && <p className="hint">Loading…</p>}
        {entries?.length === 0 && <p className="hint">Nothing written yet.</p>}

        {entries && entries.length > 0 && (
          <div className="table-wrap history">
            <table>
              <thead>
                <tr>
                  <th>when</th>
                  <th>playlist</th>
                  <th className="num">added</th>
                  <th className="num">removed</th>
                  <th className="num">coverage</th>
                  <th>backup</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry, position) => (
                  <tr key={`${entry.syncedAt}-${entry.playlistId}-${position}`}>
                    <td className="mono">{formatWhen(entry.syncedAt)}</td>
                    <td title={entry.playlistName}>{entry.playlistName || entry.playlistId}</td>
                    <td className="num">{entry.added ? `+${entry.added}` : "—"}</td>
                    <td className="num">{entry.removed ? `−${entry.removed}` : "—"}</td>
                    <td className="num">{entry.coveragePercent}%</td>
                    <td className="mono muted" title={entry.backupPath}>
                      {entry.backupPath ? entry.backupPath.split("/").pop() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="modal-actions">
          <button className="ghost" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
