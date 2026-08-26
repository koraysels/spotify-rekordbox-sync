import { useEffect, useState } from "react";

import { rpc } from "../rpc";
import { Spinner } from "./Spinner";
import type { Playlist, PlaylistPlan } from "../types";

interface RbPlaylist {
  id: string;
  name: string;
  trackCount: number;
}

interface Props {
  playlists: Playlist[];
  selected: Set<string>;
  plans: Map<string, PlaylistPlan>;
  busy: boolean;
  rekordboxRunning: boolean;
  hasPlan: boolean;
  onToggle: (id: string) => void;
  onSelectAll: () => void;
  onSelectNone: () => void;
  onPlan: () => void;
  onApply: () => void;
  refreshKey: number;
}

/**
 * The sync overview: what is on Spotify, what is in rekordbox, and the one
 * action that moves the first into the second.
 *
 * The track-level detail lives in the Tracks view. This screen answers the
 * question people actually open the app with — "what will happen, and to what?"
 */
export function SyncView({
  playlists,
  selected,
  plans,
  busy,
  rekordboxRunning,
  hasPlan,
  onToggle,
  onSelectAll,
  onSelectNone,
  onPlan,
  onApply,
  refreshKey,
}: Props) {
  const [rbPlaylists, setRbPlaylists] = useState<RbPlaylist[] | null>(null);
  const [rbError, setRbError] = useState<string | null>(null);

  useEffect(() => {
    setRbError(null);
    rpc
      .call<{ playlists: RbPlaylist[] }>("rekordbox.playlists")
      .then((result) => setRbPlaylists(result.playlists))
      .catch((cause) => {
        setRbPlaylists([]);
        setRbError(cause instanceof Error ? cause.message : String(cause));
      });
  }, [refreshKey]);

  const chosen = playlists.filter((p) => selected.has(p.id));
  const existingNames = new Set((rbPlaylists ?? []).map((p) => p.name));
  // Selected playlists that rekordbox does not have yet are shown as ghosts, so
  // the right-hand side previews the result rather than only the past.
  const pending = chosen.filter((p) => !existingNames.has(p.name));

  const totalToAdd = [...plans.values()].reduce((sum, plan) => sum + plan.toAdd.length, 0);
  const totalToRemove = [...plans.values()].reduce(
    (sum, plan) => sum + plan.toRemove.length,
    0,
  );

  return (
    <div className="syncview">
      <section className="syncpane">
        <header className="syncpane-head">
          <h2>Spotify</h2>
          <span className="syncpane-actions">
            <button className="link" onClick={onSelectAll}>
              all
            </button>
            <button className="link" onClick={onSelectNone}>
              none
            </button>
          </span>
        </header>
        <ul className="synclist">
          {playlists.map((playlist) => {
            const plan = plans.get(playlist.id);
            return (
              <li
                key={playlist.id}
                className={selected.has(playlist.id) ? "syncrow picked" : "syncrow"}
                onClick={() => onToggle(playlist.id)}
              >
                <input
                  type="checkbox"
                  checked={selected.has(playlist.id)}
                  onChange={() => onToggle(playlist.id)}
                  onClick={(event) => event.stopPropagation()}
                />
                <span className="syncrow-name" title={playlist.name}>
                  {playlist.name}
                </span>
                <span className="syncrow-meta">
                  {plan ? `${plan.coverage.percent}%` : `${playlist.trackCount}`}
                </span>
              </li>
            );
          })}
          {playlists.length === 0 && <li className="empty">No playlists.</li>}
        </ul>
      </section>

      <section className="syncmiddle">
        <Arrow active={selected.size > 0} />

        <div className="syncmiddle-summary">
          {selected.size === 0 ? (
            <p className="hint">Tick playlists on the left.</p>
          ) : hasPlan ? (
            <p className="hint">
              <strong>
                +{totalToAdd} track{totalToAdd === 1 ? "" : "s"}
              </strong>
              {totalToRemove > 0 ? ` · −${totalToRemove} to remove` : ""}
              <br />
              across {selected.size} playlist{selected.size === 1 ? "" : "s"}
            </p>
          ) : (
            <p className="hint">
              {selected.size} playlist{selected.size === 1 ? "" : "s"} selected
            </p>
          )}
        </div>

        <div className="syncmiddle-actions">
          <button
            className="primary big"
            disabled={selected.size === 0 || busy}
            onClick={onPlan}
          >
            {busy ? <Spinner size={14} label="Working…" /> : `Plan sync (${selected.size})`}
          </button>
          <button
            className="danger big"
            disabled={!hasPlan || busy || rekordboxRunning}
            onClick={onApply}
            title={
              rekordboxRunning
                ? "Quit rekordbox before writing to your library."
                : "Write the previewed changes into rekordbox"
            }
          >
            Apply to rekordbox
          </button>
          {rekordboxRunning && (
            <p className="hint warn">Quit rekordbox first — it must be closed to write.</p>
          )}
        </div>
      </section>

      <section className="syncpane">
        <header className="syncpane-head">
          <h2>rekordbox</h2>
          <span className="syncpane-actions muted">Spotify folder</span>
        </header>
        <ul className="synclist">
          {rbPlaylists === null && (
            <li className="playlists-loading">
              <Spinner size={13} label="Reading rekordbox…" />
            </li>
          )}
          {rbPlaylists?.map((playlist) => (
            <li key={playlist.id} className="syncrow">
              <span className="syncrow-name" title={playlist.name}>
                {playlist.name}
              </span>
              <span className="syncrow-meta">{playlist.trackCount}</span>
            </li>
          ))}
          {pending.map((playlist) => (
            <li key={`pending-${playlist.id}`} className="syncrow ghost">
              <span className="syncrow-name" title={playlist.name}>
                {playlist.name}
              </span>
              <span className="syncrow-meta">new</span>
            </li>
          ))}
          {rbPlaylists?.length === 0 && pending.length === 0 && !rbError && (
            <li className="empty">
              Nothing here yet. The <code>Spotify</code> folder is created the first time
              you apply a sync.
            </li>
          )}
          {rbError && <li className="empty warn">{rbError}</li>}
        </ul>
      </section>
    </div>
  );
}

function Arrow({ active }: { active: boolean }) {
  return (
    <svg
      className={active ? "syncarrow active" : "syncarrow"}
      viewBox="0 0 200 90"
      aria-hidden="true"
    >
      <defs>
        {/* userSpaceOnUse: an objectBoundingBox gradient degenerates on the
            zero-height bounding box of a horizontal line, leaving the shaft
            invisible. */}
        <linearGradient
          id="arrowfill"
          gradientUnits="userSpaceOnUse"
          x1="0"
          y1="45"
          x2="200"
          y2="45"
        >
          <stop offset="0" stopColor="#FF9A4D" />
          <stop offset="1" stopColor="#EE3D6B" />
        </linearGradient>
      </defs>
      <path
        d="M 14 45 L 122 45"
        stroke="url(#arrowfill)"
        strokeWidth="24"
        strokeLinecap="round"
        fill="none"
      />
      <path d="M 112 6 L 194 45 L 112 84 Z" fill="url(#arrowfill)" />
    </svg>
  );
}
