import { useEffect, useState } from "react";

import { rpc } from "../rpc";
import { Spinner } from "./Spinner";
import type { Playlist, PlaylistPlan } from "../types";

interface RbNode {
  id: string;
  name: string;
  parentId: string;
  isFolder: boolean;
  trackCount: number;
}

interface FlatNode extends RbNode {
  depth: number;
}

/** Flatten the tree into rows, so it renders exactly as rekordbox shows it. */
function flatten(nodes: RbNode[]): FlatNode[] {
  const byParent = new Map<string, RbNode[]>();
  for (const node of nodes) {
    const siblings = byParent.get(node.parentId) ?? [];
    siblings.push(node);
    byParent.set(node.parentId, siblings);
  }
  for (const siblings of byParent.values()) {
    siblings.sort((a, b) => {
      if (a.isFolder !== b.isFolder) return a.isFolder ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  }

  const out: FlatNode[] = [];
  const walk = (parentId: string, depth: number) => {
    for (const node of byParent.get(parentId) ?? []) {
      out.push({ ...node, depth });
      if (node.isFolder) walk(node.id, depth + 1);
    }
  };
  walk("root", 0);
  return out;
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
  const [rbNodes, setRbNodes] = useState<RbNode[] | null>(null);
  const [rbError, setRbError] = useState<string | null>(null);

  useEffect(() => {
    setRbError(null);
    rpc
      .call<{ nodes: RbNode[] }>("rekordbox.tree")
      .then((result) => setRbNodes(result.nodes))
      .catch((cause) => {
        setRbNodes([]);
        setRbError(cause instanceof Error ? cause.message : String(cause));
      });
  }, [refreshKey]);

  const rows = flatten(rbNodes ?? []);
  const spotifyFolder = (rbNodes ?? []).find((n) => n.isFolder && n.name === "Spotify");
  const chosen = playlists.filter((p) => selected.has(p.id));
  const existingNames = new Set(
    (rbNodes ?? []).filter((n) => n.parentId === spotifyFolder?.id).map((n) => n.name),
  );
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
                  {plan ? (
                    <>
                      <span className="pct">{plan.coverage.percent}%</span>
                      <span className="of">{playlist.trackCount}</span>
                    </>
                  ) : (
                    <span className="of">{playlist.trackCount}</span>
                  )}
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
          <span className="syncpane-actions muted">
            {rbNodes ? `${rbNodes.length} playlists` : "your library"}
          </span>
        </header>
        <ul className="synclist">
          {rbNodes === null && (
            <li className="playlists-loading">
              <Spinner size={13} label="Reading rekordbox…" />
            </li>
          )}

          {rows.map((node) => (
            <li
              key={node.id}
              className={
                node.id === spotifyFolder?.id ? "syncrow tree spotify-folder" : "syncrow tree"
              }
              style={{ paddingLeft: 14 + node.depth * 16 }}
            >
              <span className="syncrow-name" title={node.name}>
                {node.isFolder ? "▸ " : ""}
                {node.name}
              </span>
              <span className="syncrow-meta">
                {node.isFolder ? "" : node.trackCount}
              </span>
            </li>
          ))}

          {/* Selected playlists rekordbox does not have yet, shown where they
              will appear: inside the Spotify folder. */}
          {pending.map((playlist) => (
            <li
              key={`pending-${playlist.id}`}
              className="syncrow tree ghost"
              style={{ paddingLeft: 14 + (spotifyFolder ? 16 : 0) }}
            >
              <span className="syncrow-name" title={playlist.name}>
                {playlist.name}
              </span>
              <span className="syncrow-meta">new</span>
            </li>
          ))}

          {rbNodes?.length === 0 && !rbError && (
            <li className="empty">No playlists in rekordbox yet.</li>
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
