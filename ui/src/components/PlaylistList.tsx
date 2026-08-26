import { Spinner } from "./Spinner";
import type { Playlist, PlaylistPlan } from "../types";

interface Props {
  playlists: Playlist[];
  selected: Set<string>;
  active: string | null;
  plans: Map<string, PlaylistPlan>;
  onToggle: (id: string) => void;
  onActivate: (id: string) => void;
  onSelectAll: () => void;
  onSelectNone: () => void;
  filter: string;
  onFilter: (value: string) => void;
  loading: boolean;
  /** Playlists whose stored plan no longer reflects current state. */
  staleIds: Set<string>;
}

export function PlaylistList({
  playlists,
  selected,
  active,
  plans,
  onToggle,
  onActivate,
  onSelectAll,
  onSelectNone,
  filter,
  onFilter,
  loading,
  staleIds,
}: Props) {
  const visible = playlists.filter((p) =>
    p.name.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <aside className="playlists">
      <div className="playlists-head">
        <input
          className="search"
          placeholder="Filter playlists"
          value={filter}
          onChange={(event) => onFilter(event.target.value)}
        />
        <div className="playlists-actions">
          <button className="link" onClick={onSelectAll}>
            all
          </button>
          <button className="link" onClick={onSelectNone}>
            none
          </button>
        </div>
      </div>

      <ul className="playlist-items">
        {visible.map((playlist) => {
          const plan = plans.get(playlist.id);
          return (
            <li
              key={playlist.id}
              className={playlist.id === active ? "playlist active" : "playlist"}
              onClick={() => onActivate(playlist.id)}
            >
              <input
                type="checkbox"
                checked={selected.has(playlist.id)}
                onChange={() => onToggle(playlist.id)}
                onClick={(event) => event.stopPropagation()}
              />
              <span className="playlist-name" title={playlist.name}>
                {playlist.name}
              </span>
              {plan?.error ? (
                <span className="coverage poor" title={plan.error}>
                  n/a
                </span>
              ) : plan ? (
                <span
                  className={
                    staleIds.has(playlist.id)
                      ? "coverage stale"
                      : coverageTone(plan.coverage.percent)
                  }
                  title={
                    staleIds.has(playlist.id)
                      ? "This playlist or your settings changed since this plan was made. Press Plan sync to refresh it."
                      : undefined
                  }
                >
                  {plan.coverage.percent}%
                  {staleIds.has(playlist.id) ? " *" : ""}
                </span>
              ) : (
                <span className="count">{playlist.trackCount}</span>
              )}
            </li>
          );
        })}
        {loading && playlists.length === 0 && (
          <li className="playlists-loading">
            <Spinner size={13} label="Loading playlists…" />
          </li>
        )}
        {!loading && visible.length === 0 && (
          <li className="empty">
            {playlists.length === 0 ? "No playlists yet." : "No playlists match."}
          </li>
        )}
      </ul>
    </aside>
  );
}

function coverageTone(percent: number): string {
  if (percent >= 80) return "coverage good";
  if (percent >= 40) return "coverage mid";
  return "coverage poor";
}
