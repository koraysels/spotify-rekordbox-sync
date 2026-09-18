import { useEffect, useMemo, useState, type ReactElement } from "react";
import { rpc } from "../rpc";
import { Spinner } from "./Spinner";

interface TreeNode {
  id: string;
  name: string;
  parentId: string;
  isFolder: boolean;
  trackCount: number;
  seq: number;
}

interface Features {
  energy: number;
  danceability: number | null;
  valence: number | null;
  tempo: number | null;
  energyLevel: number;
}

type ScanStatus = "ready" | "tagged" | "unresolved" | "no-data" | "pending";

interface ScanRow {
  contentId: string;
  display: string;
  bpm: number;
  key: string;
  source: "isrc" | "spotify" | "";
  spotifyId: string;
  features: Features | null;
  energyLevel: number | null;
  danceLevel: number | null;
  moodLevel: number | null;
  taggedEnergy: number | null;
  commentEnergy: number | null;
  status: ScanStatus;
}

type SortKey = "display" | "bpm" | "key" | "energy" | "dance" | "mood";

interface Props {
  onClose: () => void;
  rekordboxRunning: boolean;
}

const ENERGY_TIP =
  "Energy 1–10: how intense and driving the track is, measured by ReccoBeats from the audio. " +
  "This is the value written as an Energy My Tag.";
const DANCE_TIP =
  "Danceability 0–100: tempo stability, beat strength and regularity. High means a steady, locked groove.";
const MOOD_TIP =
  "Mood (valence) 0–100: dark or tense at the low end, bright or euphoric at the high end. Independent of energy.";

const STATUS_LABEL: Record<ScanStatus, string> = {
  ready: "to tag",
  tagged: "tagged",
  unresolved: "not found",
  "no-data": "no data",
  pending: "not looked up",
};

const STATUS_TIP: Record<ScanStatus, string> = {
  ready: "Energy is known and not yet written as a My Tag",
  tagged: "Already carries this Energy My Tag",
  unresolved: "No confident match on Spotify, so no audio features",
  "no-data": "Found on Spotify, but ReccoBeats has no features for it",
  pending: "Spotify search was unavailable during this scan",
};

/**
 * Energy for tracks already in rekordbox playlists.
 *
 * Scans are incremental: lookups and features are cached, so re-scanning a
 * playlist only costs network calls for tracks added since.
 */
export function EnergyPanel({ onClose, rekordboxRunning }: Props) {
  const [nodes, setNodes] = useState<TreeNode[] | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [rows, setRows] = useState<ScanRow[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [minEnergy, setMinEnergy] = useState(1);
  const [overwriteMik, setOverwriteMik] = useState(false);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "energy", desc: true });

  useEffect(() => {
    rpc
      .call<{ nodes: TreeNode[] }>("rekordbox.tree")
      .then((result) => setNodes(result.nodes))
      .catch((cause) => setError(message(cause)));
    const off = rpc.onProgress?.((text: string) => setBusy((current) => (current ? text : current)));
    return () => off?.();
  }, []);

  const children = useMemo(() => {
    const map = new Map<string, TreeNode[]>();
    for (const node of nodes ?? []) {
      const list = map.get(node.parentId) ?? [];
      list.push(node);
      map.set(node.parentId, list);
    }
    for (const list of map.values()) list.sort((a, b) => a.seq - b.seq);
    return map;
  }, [nodes]);

  const scan = async () => {
    setError(null);
    setNotice(null);
    setBusy("Scanning…");
    try {
      const result = await rpc.call<{ tracks: ScanRow[]; searchError: string }>("energy.scan", {
        playlistIds: [...chosen],
      });
      setRows(result.tracks);
      if (result.searchError) {
        setNotice(`Spotify lookup unavailable, only tracks with an ISRC were checked: ${result.searchError}`);
      }
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(null);
    }
  };

  /** Tracks whose tag would be written: a known level, and not a Mixed In Key value unless allowed. */
  const writable = useMemo(
    () =>
      (rows ?? []).filter(
        (row) =>
          row.status === "ready" &&
          row.energyLevel !== null &&
          row.energyLevel >= minEnergy &&
          (overwriteMik || row.commentEnergy === null),
      ),
    [rows, minEnergy, overwriteMik],
  );

  const apply = async () => {
    setError(null);
    setBusy("Writing energy tags…");
    try {
      // Energy, Dance and Mood together; any that are unknown are left out.
      const levels = Object.fromEntries(
        writable.map((row) => [
          row.contentId,
          Object.fromEntries(
            (
              [
                ["Energy", row.energyLevel],
                ["Dance", row.danceLevel],
                ["Mood", row.moodLevel],
              ] as const
            ).filter(([, value]) => value !== null && value !== undefined),
          ),
        ]),
      );
      const result = await rpc.call<{ changed: number; backupPath: string }>("energy.apply", { levels });
      setNotice(`Tagged ${result.changed} track${result.changed === 1 ? "" : "s"} in rekordbox. Backup taken first.`);
      await scan();
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(null);
    }
  };

  const shown = useMemo(() => {
    const list = (rows ?? []).filter((row) => (row.energyLevel ?? 0) >= minEnergy || minEnergy === 1);
    const value = (row: ScanRow): number | string => {
      switch (sort.key) {
        case "display":
          return row.display.toLowerCase();
        case "bpm":
          return row.bpm;
        case "key":
          return row.key;
        case "energy":
          return row.energyLevel ?? row.commentEnergy ?? -1;
        case "dance":
          return row.features?.danceability ?? -1;
        case "mood":
          return row.features?.valence ?? -1;
      }
    };
    return [...list].sort((a, b) => {
      const left = value(a);
      const right = value(b);
      const order = left < right ? -1 : left > right ? 1 : 0;
      return sort.desc ? -order : order;
    });
  }, [rows, minEnergy, sort]);

  const counts = useMemo(() => {
    const result: Record<ScanStatus, number> = { ready: 0, tagged: 0, unresolved: 0, "no-data": 0, pending: 0 };
    for (const row of rows ?? []) result[row.status] += 1;
    return result;
  }, [rows]);

  const header = (key: SortKey, label: string, className = "", tip = "") => (
    <th
      className={`sortable ${className}`}
      title={tip ? `${tip}\n\nClick to sort.` : "Click to sort."}
      onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== "display" }))}
    >
      {label}
      {sort.key === key ? (sort.desc ? " ↓" : " ↑") : ""}
    </th>
  );

  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChosen(next);
  };

  const renderTree = (parentId: string, depth: number): ReactElement[] =>
    (children.get(parentId) ?? []).flatMap((node) => [
      <label key={node.id} className="energy-tree-row" style={{ paddingLeft: 8 + depth * 14 }}>
        <input type="checkbox" checked={chosen.has(node.id)} onChange={() => toggle(node.id)} />
        <span className={node.isFolder ? "folder-name" : ""}>
          {node.isFolder ? "▸ " : ""}
          {node.name}
        </span>
        {!node.isFolder && <span className="muted num">{node.trackCount}</span>}
      </label>,
      ...(node.isFolder ? renderTree(node.id, depth + 1) : []),
    ]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal energy-modal" onClick={(event) => event.stopPropagation()}>
        <h2>Energy</h2>
        <p className="hint">
          Pick rekordbox playlists or folders and scan them. Each track is looked up on Spotify, its audio
          features come from ReccoBeats, and energy, dance and mood (1–10) are written back as{" "}
          <code>Energy N</code>, <code>Dance N</code> and <code>Mood N</code> My Tags, in a My Tag column
          called <code>Vibe</code>. Tracks that already have a Mixed In Key energy in their comment are
          left alone unless you allow it.
        </p>

        {error && <div className="banner error">{error}</div>}
        {notice && <div className="banner info">{notice}</div>}

        <div className="energy-layout">
          <div className="energy-tree">
            {nodes === null ? <Spinner /> : renderTree("root", 0)}
          </div>

          <div className="energy-results">
            {rows === null ? (
              <p className="muted">
                {chosen.size === 0 ? "Choose playlists on the left." : `${chosen.size} selected. Press Scan.`}
              </p>
            ) : (
              <>
                <div className="energy-toolbar">
                  {(Object.keys(counts) as ScanStatus[])
                    .filter((status) => counts[status] > 0)
                    .map((status) => (
                      <span key={status} className={`band energy-${status}`} title={STATUS_TIP[status]}>
                        {STATUS_LABEL[status]} {counts[status]}
                      </span>
                    ))}
                  <label className="energy-filter">
                    min energy
                    <input
                      type="range"
                      min={1}
                      max={10}
                      value={minEnergy}
                      onChange={(event) => setMinEnergy(Number(event.target.value))}
                    />
                    <span className="num">{minEnergy}</span>
                  </label>
                  <label className="energy-filter">
                    <input
                      type="checkbox"
                      checked={overwriteMik}
                      onChange={(event) => setOverwriteMik(event.target.checked)}
                    />
                    also tag Mixed In Key tracks
                  </label>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th className="col-band">state</th>
                        {header("display", "track")}
                        {header("bpm", "bpm", "col-score", "Tempo from rekordbox's analysis of the file.")}
                        {header("key", "key", "col-score", "Musical key from rekordbox's analysis.")}
                        {header("energy", "energy", "col-score", ENERGY_TIP)}
                        {header("dance", "dance", "col-score", DANCE_TIP)}
                        {header("mood", "mood", "col-score", MOOD_TIP)}
                      </tr>
                    </thead>
                    <tbody>
                      {shown.map((row) => (
                        <tr key={row.contentId}>
                          <td className="col-band">
                            <span className={`band energy-${row.status}`} title={STATUS_TIP[row.status]}>
                              {STATUS_LABEL[row.status]}
                            </span>
                          </td>
                          <td title={row.display}>{row.display}</td>
                          <td className="col-score">{row.bpm ? row.bpm.toFixed(0) : "—"}</td>
                          <td className="col-score">{row.key || "—"}</td>
                          <td className="col-score">
                            <EnergyCell row={row} />
                          </td>
                          <td className="col-score">{pct(row.features?.danceability)}</td>
                          <td className="col-score">{pct(row.features?.valence)}</td>
                        </tr>
                      ))}
                      {shown.length === 0 && (
                        <tr>
                          <td colSpan={7} className="empty">
                            No tracks.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </div>

        <div className="modal-actions">
          {busy ? (
            <span className="muted">
              <Spinner /> {busy}
            </span>
          ) : (
            rekordboxRunning &&
            writable.length > 0 && (
              // Said out loud, not only in a tooltip: a disabled-looking button
              // with no reason is what made this seem broken. The core checks
              // again when writing, so a stale "running" never blocks.
              <span className="hint warn">Quit rekordbox completely before tagging.</span>
            )
          )}
          <button onClick={onClose}>Close</button>
          <button disabled={chosen.size === 0 || busy !== null} onClick={() => void scan()}>
            Scan
          </button>
          <button
            className="primary"
            disabled={writable.length === 0 || busy !== null}
            title="Writes Energy, Dance and Mood My Tags. rekordbox must be closed; a backup is made first."
            onClick={() => void apply()}
          >
            Tag {writable.length} in rekordbox
          </button>
        </div>
      </div>
    </div>
  );
}

function EnergyCell({ row }: { row: ScanRow }) {
  if (row.energyLevel === null && row.commentEnergy === null) return <span className="muted">—</span>;
  return (
    <span className="energy-cell">
      {row.energyLevel !== null && (
        <span className={`energy-pill e${row.energyLevel}`} title={`ReccoBeats energy ${row.features?.energy.toFixed(2)}`}>
          {row.energyLevel}
        </span>
      )}
      {row.commentEnergy !== null && (
        <span className="energy-mik" title="Energy from Mixed In Key, found in the comment">
          MIK {row.commentEnergy}
        </span>
      )}
    </span>
  );
}

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}`;
}

function message(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}
