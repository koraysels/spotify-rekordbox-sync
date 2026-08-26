import { Spinner } from "./Spinner";
import type { Status } from "../types";

interface Props {
  status: Status | null;
  busy: string | null;
  onSettings: () => void;
  onHistory: () => void;
  onLibrary: () => void;
  view: "sync" | "tracks";
  onView: (value: "sync" | "tracks") => void;
}

export function StatusBar({
  status,
  busy,
  onSettings,
  onHistory,
  onLibrary,
  view,
  onView,
}: Props) {
  return (
    <header className="statusbar" data-tauri-drag-region>
      <div className="statusbar-items">
        <Item
          label="rekordbox"
          value={status?.rekordbox_running ? "running" : "closed"}
          tone={status?.rekordbox_running ? "warn" : "ok"}
          title={
            status?.rekordbox_running
              ? "Rekordbox must be closed before writing. Quit it completely."
              : status?.db_path ?? "No database found"
          }
        />
        <Item
          label="collection"
          value={status?.tracks_indexed ? `${status.tracks_indexed.toLocaleString()} tracks` : "not loaded"}
          tone={status?.tracks_indexed ? "ok" : "idle"}
        />
        <Item
          label="spotify"
          value={status?.authenticated ? "connected" : "not connected"}
          tone={status?.authenticated ? "ok" : "idle"}
        />
      </div>
      <div className="statusbar-right">
        <span className="viewtabs">
          <button className={view === "sync" ? "on" : ""} onClick={() => onView("sync")}>
            Sync
          </button>
          <button className={view === "tracks" ? "on" : ""} onClick={() => onView("tracks")}>
            Tracks
          </button>
        </span>
        {busy && (
          <span className="busy">
            <Spinner size={12} label={busy} />
          </span>
        )}
        <button className="ghost" onClick={onLibrary}>
          In rekordbox
        </button>
        <button className="ghost" onClick={onHistory}>
          History
        </button>
        <button className="ghost" onClick={onSettings}>
          Settings
        </button>
      </div>
    </header>
  );
}

function Item({
  label,
  value,
  tone,
  title,
}: {
  label: string;
  value: string;
  tone: "ok" | "warn" | "idle";
  title?: string;
}) {
  return (
    <span className="status-item" title={title}>
      <span className="status-label">{label}</span>
      <span className={`status-value ${tone}`}>{value}</span>
    </span>
  );
}
