import { useEffect, useState } from "react";
import { rpc } from "../rpc";

interface RbPlaylist {
  id: string;
  name: string;
  trackCount: number;
}

interface Health {
  ok: number;
  missing: number;
  offline: number;
  unknown: number;
  total: number;
  volumes: { volume: string; count: number }[];
}

interface Props {
  onClose: () => void;
}

/**
 * What is actually inside rekordbox right now.
 *
 * Read from master.db rather than from our own sync records, so it answers
 * "did it really land?" rather than "did we think it landed?".
 */
export function RekordboxPanel({ onClose }: Props) {
  const [playlists, setPlaylists] = useState<RbPlaylist[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    rpc
      .call<{ playlists: RbPlaylist[] }>("rekordbox.playlists")
      .then((result) => setPlaylists(result.playlists))
      .catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
    rpc
      .call<Health>("library.health")
      .then(setHealth)
      .catch(() => {
        // Health is extra information; the playlist list is the main content.
      });
  }, []);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <h2>In rekordbox</h2>
        <p className="hint">
          The playlists inside rekordbox's <code>Spotify</code> folder, read straight from
          its database.
        </p>

        {health && (
          <>
            <h3>Your collection</h3>
            <div className="health">
              <div className="health-row">
                <span>Playable now</span>
                <span className="num">
                  {health.ok.toLocaleString()} of {health.total.toLocaleString()}
                </span>
              </div>
              {health.offline > 0 && (
                <div className="health-row">
                  <span>On a drive that is not connected</span>
                  <span className="num">{health.offline.toLocaleString()}</span>
                </div>
              )}
              {health.missing > 0 && (
                <div className="health-row">
                  <span>File moved or deleted</span>
                  <span className="num">{health.missing.toLocaleString()}</span>
                </div>
              )}
            </div>
            {health.volumes.length > 0 && (
              <p className="hint">
                Reconnect{" "}
                {health.volumes.map((entry, index) => (
                  <span key={entry.volume}>
                    {index > 0 ? ", " : ""}
                    <code>{entry.volume.replace("/Volumes/", "")}</code> (
                    {entry.count.toLocaleString()} tracks)
                  </span>
                ))}{" "}
                to make those playable again. Syncing still works without them — rekordbox
                stores the path, so the tracks light up when the drive is back.
              </p>
            )}
          </>
        )}

        {error && <p className="hint warn">{error}</p>}
        {!playlists && !error && <p className="hint">Reading rekordbox…</p>}
        {playlists?.length === 0 && (
          <p className="hint">
            Nothing yet — no <code>Spotify</code> folder exists in rekordbox. It is created
            the first time you apply a sync.
          </p>
        )}

        {playlists && playlists.length > 0 && (
          <div className="table-wrap history">
            <table>
              <thead>
                <tr>
                  <th>playlist</th>
                  <th className="num">tracks</th>
                </tr>
              </thead>
              <tbody>
                {playlists.map((playlist) => (
                  <tr key={playlist.id}>
                    <td title={playlist.name}>{playlist.name}</td>
                    <td className="num">{playlist.trackCount}</td>
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
