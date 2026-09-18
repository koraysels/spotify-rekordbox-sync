import type { ReactNode } from "react";
import type { Candidate, TrackFeatures, TrackPlan } from "../types";
import type { FileStatus } from "./TrackTable";
import { camelotOf } from "../keys";

interface Props {
  row: TrackPlan;
  file?: FileStatus;
  features?: TrackFeatures;
  onClose: () => void;
  onChooseMatch: () => void;
  onUndoDecision: () => void;
}


const BAND_TEXT = {
  accept: "Matched",
  review: "Needs review",
  reject: "Missing",
} as const;

/**
 * Everything known about one row, in one place: the Spotify track, the file it
 * matched, why it matched, and any decision you made about it.
 */
export function TrackInfoPanel({ row, file, features, onClose, onChooseMatch, onUndoDecision }: Props) {
  const matched: Candidate | undefined =
    row.band === "reject"
      ? undefined
      : row.candidates.find((c) => c.contentId === row.contentId) ?? row.candidates[0];
  const spotifySeconds = row.track.durationMs / 1000;
  const others = row.candidates.filter((c) => c !== matched);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal track-info" onClick={(event) => event.stopPropagation()}>
        <h2>{row.track.display}</h2>
        <p className="hint">
          <span className={`band ${row.band}`}>{BAND_TEXT[row.band]}</span> {explainReason(row)}
        </p>

        <div className="info-columns">
          <section>
            <h3>Spotify</h3>
            <Field label="Title">{row.track.name}</Field>
            <Field label="Artists">{row.track.artists.join(", ")}</Field>
            <Field label="Album">{row.track.album || "—"}</Field>
            <Field label="Length">{formatSeconds(spotifySeconds)}</Field>
            <Field label="ISRC">
              <span className="mono">{row.track.isrc || "—"}</span>
            </Field>
            <Field label="Spotify ID">
              <span className="mono">{row.track.id}</span>
            </Field>
            {features ? (
              <>
                <Field label="Energy">
                  <span className={`energy-pill e${features.energyLevel}`}>{features.energyLevel}</span>{" "}
                  <span className="muted">({features.energy.toFixed(2)})</span>
                </Field>
                <Field label="Danceability">{pct(features.danceability)}</Field>
                <Field label="Mood (valence)">{pct(features.valence)}</Field>
                <Field label="Tempo">{features.tempo ? `${features.tempo.toFixed(1)} BPM` : "—"}</Field>
                <Field label="Key">{spotifyKey(features)}</Field>
                <Field label="Instrumental">{pct(features.instrumentalness)}</Field>
                <Field label="Acoustic">{pct(features.acousticness)}</Field>
                <Field label="Loudness">
                  {features.loudness !== null ? `${features.loudness.toFixed(1)} dB` : "—"}
                </Field>
              </>
            ) : (
              <Field label="Audio features">
                <span className="muted">not loaded</span>
              </Field>
            )}
          </section>

          <section>
            <h3>rekordbox</h3>
            {matched ? (
              <>
                <Field label="Track">{matched.display}</Field>
                <Field label="Length">
                  {formatSeconds(matched.lengthSeconds)}{" "}
                  <LengthDiff seconds={matched.lengthSeconds} spotifySeconds={spotifySeconds} />
                </Field>
                <Field label="BPM">{matched.bpm ? matched.bpm.toFixed(1) : "—"}</Field>
                <Field label="Key">{matched.key || "—"}</Field>
                <Field label="Bitrate">{matched.bitRate ? `${matched.bitRate} kbps` : "—"}</Field>
                <Field label="File">
                  <span className="mono">{matched.fileName || "—"}</span>
                </Field>
                <Field label="Location">
                  <span className="mono path">{file?.path || matched.folderPath || "—"}</span>
                </Field>
                <Field label="File status">{fileStatus(file)}</Field>
                <Field label="Match confidence">
                  <strong>{matched.score.toFixed(2)}</strong>{" "}
                  <span className="muted">
                    title {matched.titleScore.toFixed(2)} · artist {matched.artistScore.toFixed(2)} · length{" "}
                    {matched.durationScore.toFixed(2)}
                  </span>
                </Field>
                <Field label="rekordbox ID">
                  <span className="mono">{matched.contentId}</span>
                </Field>
              </>
            ) : (
              <p className="muted">
                {row.reason === "rejected"
                  ? "You rejected every file for this track."
                  : "No file in your collection is close enough to count as this track."}
              </p>
            )}

            {others.length > 0 && (
              <>
                <h3 className="info-subhead">Other candidates</h3>
                <ul className="info-candidates">
                  {others.map((candidate) => (
                    <li key={candidate.contentId}>
                      <span>{candidate.display}</span>
                      <span className="muted">
                        {formatSeconds(candidate.lengthSeconds)} · {candidate.score.toFixed(2)}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        </div>

        <div className="modal-actions">
          {(row.reason === "rejected" || row.reason === "cached") && (
            <button className="link" onClick={onUndoDecision}>
              undo decision
            </button>
          )}
          <button onClick={onChooseMatch}>Choose match…</button>
          <button className="primary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="info-field">
      <span className="info-label">{label}</span>
      <span className="info-value">{children}</span>
    </div>
  );
}

function LengthDiff({ seconds, spotifySeconds }: { seconds: number; spotifySeconds: number }) {
  const delta = Math.round(seconds - spotifySeconds);
  if (Math.abs(delta) < 5) return <span className="muted">same as Spotify</span>;
  return (
    <span className="len-diff">
      {Math.abs(delta)}s {delta > 0 ? "longer" : "shorter"} than Spotify — possibly another version
    </span>
  );
}

function explainReason(row: TrackPlan): string {
  switch (row.reason) {
    case "isrc":
      return "Same ISRC as a file in your collection: an exact identifier match.";
    case "cached":
      return "You chose this match yourself earlier.";
    case "rejected":
      return "You rejected a match for this track earlier; other files are shown for review.";
    case "other-version":
      return "Same title and artist, but a clearly different length: probably another version.";
    case "mix-mismatch":
      return "Title matches, but the mix names differ (e.g. remix vs original).";
    case "no-candidates":
      return "Nothing in your collection came close.";
    default:
      return "";
  }
}

function fileStatus(file?: FileStatus): ReactNode {
  if (!file) return <span className="muted">not checked</span>;
  switch (file.status) {
    case "ok":
      return <span className="ok-text">on disk, plays</span>;
    case "offline":
      return <span className="len-diff">on {file.volume.replace("/Volumes/", "")}, which is not connected</span>;
    case "missing":
      return <span className="danger-text">file moved or deleted</span>;
    default:
      return <span className="muted">unknown</span>;
  }
}

function spotifyKey(features: TrackFeatures): string {
  return camelotOf(features) || "—";
}

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}`;
}

function formatSeconds(seconds: number): string {
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
