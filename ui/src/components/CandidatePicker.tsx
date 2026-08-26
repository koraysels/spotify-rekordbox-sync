import type { TrackPlan } from "../types";

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
                  <th>file</th>
                  <th className="num">length</th>
                  <th className="num">kbps</th>
                  <th className="num">score</th>
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
                    <td className="mono muted" title={candidate.folderPath}>
                      {candidate.fileName}
                    </td>
                    <td className="num">{formatSeconds(candidate.lengthSeconds)}</td>
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

function formatDuration(ms: number): string {
  return formatSeconds(ms / 1000);
}

function formatSeconds(seconds: number): string {
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, "0")}`;
}
