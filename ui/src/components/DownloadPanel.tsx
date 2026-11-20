import { revealPath } from "../reveal";
import type { DownloadJob, DownloadRecord, DownloaderStatus } from "../types";

interface Props {
  jobs: Map<string, DownloadJob>;
  records: Map<string, DownloadRecord>;
  status: DownloaderStatus | null;
  /** Spotify id to "artist - title", for the tracks on screen. */
  titles: Map<string, string>;
  onCancelAll: () => void;
  onResume: () => void;
  onClose: () => void;
}

const ACTIVE = new Set(["queued", "downloading", "converting"]);

export function DownloadPanel({ jobs, records, status, titles, onCancelAll, onResume, onClose }: Props) {
  const list = [...jobs.values()];
  const active = list.filter((job) => ACTIVE.has(job.state));

  // Finished downloads, grouped by the playlist they were fetched for.
  const folders = new Map<string, { count: number; path: string }>();
  for (const record of records.values()) {
    if (record.status !== "done" || !record.exists) continue;
    const entry = folders.get(record.playlistName) ?? { count: 0, path: record.path };
    entry.count += 1;
    folders.set(record.playlistName, entry);
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wide" onClick={(event) => event.stopPropagation()}>
        <h2>Downloads</h2>

        {status?.paused && (
          <p className="hint warn">
            Downloads are paused{status.reason ? `: ${status.reason}` : "."}{" "}
            <button className="link" onClick={onResume}>
              Resume
            </button>
          </p>
        )}
        {list.length === 0 && <p className="hint">No downloads yet.</p>}

        {list.length > 0 && (
          <div className="download-list">
            {list.map((job) => {
              const title = titles.get(job.spotifyId) ?? (job.name || job.spotifyId);
              return (
                <div className="download-row" key={job.jobId}>
                  <span title={title}>{title}</span>
                  <span className="muted" title={job.message}>
                    {job.state}
                    {job.message ? ` · ${job.message}` : ""}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {[...folders].map(([name, { count, path }]) => {
          const folder = folderOf(path);
          return (
            <div className="download-row" key={name}>
              <span title={folder}>
                {count} track{count === 1 ? "" : "s"} in <code>{folder}</code>
              </span>
              <button className="chip" onClick={() => void revealPath(path)}>
                Show in Finder
              </button>
            </div>
          );
        })}

        <div className="modal-actions">
          <button className="ghost" disabled={active.length === 0} onClick={onCancelAll}>
            Cancel all
          </button>
          <button className="ghost" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

/** The folder a file sits in; handles both `/` and `\\` separators. */
function folderOf(path: string): string {
  return path.slice(0, Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"))) || path;
}
