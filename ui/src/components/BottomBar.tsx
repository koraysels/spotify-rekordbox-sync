import type { Coverage } from "../types";

interface Props {
  selectedCount: number;
  coverage: Coverage | null;
  hasPlan: boolean;
  rekordboxRunning: boolean;
  busy: boolean;
  onPlan: () => void;
  onApply: () => void;
  onExport: () => void;
}

export function BottomBar({
  selectedCount,
  coverage,
  hasPlan,
  rekordboxRunning,
  busy,
  onPlan,
  onApply,
  onExport,
}: Props) {
  return (
    <footer className="bottombar">
      <div className="summary">
        {coverage ? (
          <>
            <strong>{coverage.percent}%</strong> matched · {coverage.matched} found ·{" "}
            {coverage.review} to review · {coverage.missing} missing
          </>
        ) : (
          <span className="muted">No plan yet.</span>
        )}
      </div>
      <div className="actions">
        <button className="ghost" disabled={!hasPlan || busy} onClick={onExport}>
          Export wantlist
        </button>
        <button className="primary" disabled={selectedCount === 0 || busy} onClick={onPlan}>
          Plan sync ({selectedCount})
        </button>
        <button
          className="danger"
          disabled={!hasPlan || busy || rekordboxRunning}
          onClick={onApply}
          title={
            rekordboxRunning
              ? "Quit rekordbox before writing to your library."
              : "Write the previewed changes to rekordbox"
          }
        >
          Apply to rekordbox
        </button>
      </div>
    </footer>
  );
}
