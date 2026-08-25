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
              {plan ? (
                <span className={coverageTone(plan.coverage.percent)}>
                  {plan.coverage.percent}%
                </span>
              ) : (
                <span className="count">{playlist.trackCount}</span>
              )}
            </li>
          );
        })}
        {visible.length === 0 && <li className="empty">No playlists match.</li>}
      </ul>
    </aside>
  );
}

function coverageTone(percent: number): string {
  if (percent >= 80) return "coverage good";
  if (percent >= 40) return "coverage mid";
  return "coverage poor";
}
