import { useEffect, useState } from "react";
import { revealItemInDir } from "@tauri-apps/plugin-opener";

import { isTauri, rpc } from "../rpc";
import type { TrackPlan } from "../types";
import type { FileStatus } from "./TrackTable";

interface Props {
  row: TrackPlan;
  onChoose: (contentId: string) => void;
  onReject: () => void;
  onClose: () => void;
}

/**
 * Pick which local file a Spotify track maps to.
 *
 * The top-scoring candidate is not always the right one: this collection holds
 * multiple copies of most tracks, and remixes score close to their originals.
 * Accepting or rejecting the single best guess is not enough control, so every
 * candidate the matcher considered is listed with the evidence behind its score.
 */
export function CandidatePicker({ row, onChoose, onReject, onClose }: Props) {
  // Whether each candidate's file is actually there. Choosing a copy on an
  // unplugged drive, or one that was deleted, puts a track in a playlist that
  // will not play, so this has to be visible before choosing.
  const [files, setFiles] = useState<Record<string, FileStatus> | null>(null);

  useEffect(() => {
    const contentIds = row.candidates.map((candidate) => candidate.contentId);
    if (contentIds.length === 0) return;
    let cancelled = false;
    rpc
      .call<{ files: Record<string, FileStatus> }>("tracks.verify", { contentIds })
      .then((result) => {
        if (!cancelled) setFiles(result.files);
      })
      .catch(() => {
        if (!cancelled) setFiles({});
      });
    return () => {
      cancelled = true;
    };
  }, [row]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal picker" onClick={(event) => event.stopPropagation()}>
        <h2>Choose match</h2>
        <p className="hint">
          <strong>{row.track.display}</strong>
          <br />
          {formatDuration(row.track.durationMs)}
          {row.track.album ? ` · ${row.track.album}` : ""}
          {row.track.isrc ? ` · ISRC ${row.track.isrc}` : ""}
        </p>

        {row.candidates.length === 0 ? (
          <p className="hint warn">
            Nothing in your collection came close enough to consider. This track goes on
            the wantlist.
          </p>
        ) : (
          <div className="table-wrap history">
            <table>
              <thead>
                <tr>
                  <th>rekordbox track</th>
                  <th>file and location</th>
                  <th title="Whether the file is on disk right now.">status</th>
                  <th className="num">length</th>
                  <th className="num">kbps</th>
                  <th
                    className="num"
                    title="How sure rbsync is that this file is the same record as the Spotify track, from 0 to 1. Title 55%, artist 30%, length 15%."
                  >
                    match conf.
                  </th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {row.candidates.map((candidate) => (
                  <tr
                    key={candidate.contentId}
                    className={candidate.contentId === row.contentId ? "row selected" : "row"}
                  >
                    <td title={candidate.display}>{candidate.display}</td>
                    <td className="picker-file" title={candidate.folderPath}>
                      <span className="mono">{candidate.fileName || "—"}</span>
                      <span className="picker-path mono muted">{folderOf(candidate.folderPath)}</span>
                    </td>
                    <td className="picker-status">
                      <FileBadge status={files?.[candidate.contentId]} loading={files === null} />
                      {candidate.folderPath && isTauri() && files?.[candidate.contentId]?.status === "ok" && (
                        <button
                          className="chip"
                          onClick={() => void revealItemInDir(candidate.folderPath).catch(() => {})}
                          title={`Show in Finder: ${candidate.folderPath}`}
                        >
                          file
                        </button>
                      )}
                    </td>
                    <td
                      className={
                        Math.abs(candidate.lengthSeconds - row.track.durationMs / 1000) >= 5 ? "num len-diff" : "num"
                      }
                      title="Length of this file. Highlighted when it differs from the Spotify version by 5 seconds or more."
                    >
                      {formatSeconds(candidate.lengthSeconds)}
                      {Math.abs(candidate.lengthSeconds - row.track.durationMs / 1000) >= 5 && (
                        <span className="len-delta">
                          {" "}
                          {candidate.lengthSeconds > row.track.durationMs / 1000 ? "+" : "−"}
                          {formatSeconds(Math.abs(candidate.lengthSeconds - row.track.durationMs / 1000))}
                        </span>
                      )}
                    </td>
                    <td className="num">{candidate.bitRate || "—"}</td>
                    <td
                      className="num"
                      title={
                        // The breakdown is diagnostic detail; keeping it in a
                        // tooltip leaves room for the action to stay visible.
                        `title ${candidate.titleScore.toFixed(2)} · ` +
                        `artist ${candidate.artistScore.toFixed(2)} · ` +
                        `duration ${candidate.durationScore.toFixed(2)}`
                      }
                    >
                      <strong>{candidate.score.toFixed(2)}</strong>
                    </td>
                    <td className="num">
                      <button className="accept" onClick={() => onChoose(candidate.contentId)}>
                        Use this
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="modal-actions">
          <button className="reject" onClick={onReject}>
            No local copy — add to wantlist
          </button>
          <button className="ghost" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function FileBadge({ status, loading }: { status?: FileStatus; loading: boolean }) {
  if (loading) return <span className="muted">checking…</span>;
  switch (status?.status) {
    case "ok":
      return <span className="band accept">on disk</span>;
    case "offline":
      return (
        <span
          className="band drive-offline"
          title={`On ${status.volume}, which is not connected. Reconnect the drive and it plays.`}
        >
          {status.volume.replace("/Volumes/", "")} offline
        </span>
      );
    case "missing":
      return (
        <span className="band missing-file" title={`Nothing at ${status.path}: moved or deleted.`}>
          no file
        </span>
      );
    default:
      return <span className="muted">unknown</span>;
  }
}

/** The folder a file sits in, with the home directory shortened. */
function folderOf(path: string): string {
  if (!path) return "";
  const folder = path.replace(/[\\/][^\\/]*$/, "");
  return folder.replace(/^\/Users\/[^/]+/, "~");
}

function formatDuration(ms: number): string {
  return formatSeconds(ms / 1000);
}

function formatSeconds(seconds: number): string {
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, "0")}`;
}
