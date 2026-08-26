import { useCallback, useEffect, useState } from "react";

import { revealPath } from "../reveal";
import { rpc } from "../rpc";
import { Spinner } from "./Spinner";

interface Backup {
  name: string;
  path: string;
  size: number;
  createdAt: string;
  isOriginal: boolean;
}

interface Props {
  onClose: () => void;
  onRestored: () => void;
}

/**
 * Backups of the rekordbox database, and the way back.
 *
 * One of them is the library exactly as it was before this app ever wrote to
 * it. That one is never pruned, because after enough syncs every rolling backup
 * is itself post-rbsync and there would be nothing original left to return to.
 */
export function BackupsPanel({ onClose, onRestored }: Props) {
  const [backups, setBackups] = useState<Backup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<Backup | null>(null);

  const load = useCallback(() => {
    rpc
      .call<{ backups: Backup[] }>("backups.list")
      .then((result) => setBackups(result.backups))
      .catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, []);

  useEffect(load, [load]);

  const createBackup = async () => {
    setBusy("Backing up…");
    setError(null);
    try {
      await rpc.call("backups.create");
      load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  const restore = async (backup: Backup) => {
    setBusy("Restoring…");
    setError(null);
    try {
      await rpc.call("backups.restore", { path: backup.path });
      setConfirming(null);
      load();
      onRestored();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setConfirming(null);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wide" onClick={(event) => event.stopPropagation()}>
        <h2>Backups</h2>
        <p className="hint">
          Your rekordbox database is copied here before every write, and the copy is
          size-checked before anything changes. Restoring puts one back — and takes a
          copy of the current state first, so a restore can itself be undone.
        </p>

        {error && <p className="hint warn">{error}</p>}
        {!backups && !error && <p className="hint">Loading…</p>}

        {backups?.length === 0 && (
          <p className="hint">
            No backups yet. One is taken automatically the first time you apply a sync, or
            take one now.
          </p>
        )}

        {backups && backups.length > 0 && (
          <div className="table-wrap history">
            <table>
              <thead>
                <tr>
                  <th>backup</th>
                  <th>taken</th>
                  <th className="num">size</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {backups.map((backup) => (
                  <tr key={backup.path}>
                    <td>
                      {backup.isOriginal ? (
                        <span className="band drive-offline">before rbsync</span>
                      ) : (
                        <span className="mono muted">{backup.name}</span>
                      )}
                    </td>
                    <td className="mono">{formatWhen(backup.createdAt)}</td>
                    <td className="num">{formatSize(backup.size)}</td>
                    <td className="num">
                      <span className="copy-actions">
                        <button className="chip" onClick={() => void revealPath(backup.path)}>
                          show
                        </button>
                        <button
                          className="chip"
                          disabled={busy !== null}
                          onClick={() => setConfirming(backup)}
                        >
                          restore
                        </button>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {confirming && (
          <div className="confirm">
            <p>
              Replace your rekordbox library with{" "}
              <strong>
                {confirming.isOriginal ? "the state before rbsync" : confirming.name}
              </strong>
              ?
            </p>
            <p className="hint warn">
              Everything in rekordbox since that backup is undone, including changes you
              made in rekordbox itself. Quit rekordbox first. The current state is copied
              aside so you can come back.
            </p>
            <div className="modal-actions">
              <button className="ghost" onClick={() => setConfirming(null)}>
                Cancel
              </button>
              <button className="danger" onClick={() => void restore(confirming)}>
                Restore it
              </button>
            </div>
          </div>
        )}

        <div className="modal-actions">
          {busy && <Spinner size={13} label={busy} />}
          <button className="ghost" disabled={busy !== null} onClick={() => void createBackup()}>
            Back up now
          </button>
          <button className="primary" onClick={onClose}>
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

function formatSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}
