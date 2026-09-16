import type { Coverage } from "../types";

interface Props {
  onOpenSync: () => void;
  selectedCount: number;
  coverage: Coverage | null;
  hasPlan: boolean;
  busy: boolean;
  onPlan: () => void;
  onExport: () => void;
}

/**
 * One way to write, one way to match.
 *
 * Writing to rekordbox goes through the Sync window, which previews and then
 * imports. The bar used to carry a second write button and a "Plan sync" that
 * actually meant "match again"; three overlapping actions read as three
 * different things.
 */
export function BottomBar({
  onOpenSync,
  selectedCount,
  coverage,
  hasPlan,
  busy,
  onPlan,
  onExport,
}: Props) {
  return (
    <footer className="bottombar">
      <button
        className="primary sync-launcher"
        onClick={onOpenSync}
        title="Open the Sync window: pick playlists, preview, and import them into rekordbox."
      >
        Import into rekordbox…
      </button>
      <div className="summary">
        {coverage ? (
          <>
            <strong>{coverage.percent}%</strong> matched · {coverage.matched} found ·{" "}
            {coverage.review} to review · {coverage.missing} missing
          </>
        ) : (
          <span className="muted">No matches yet. Select playlists and press Find matches.</span>
        )}
      </div>
      <div className="actions">
        <button className="ghost" disabled={!hasPlan || busy} onClick={onExport}>
          Export wantlist
        </button>
        <button
          className="ghost"
          disabled={selectedCount === 0 || busy}
          onClick={onPlan}
          title={
            "Read your rekordbox collection and the selected Spotify playlists again, and match " +
            "every track from scratch. Picks up files you imported since. Your accept/reject " +
            "decisions are kept. Nothing is written to rekordbox."
          }
        >
          Find matches ({selectedCount})
        </button>
      </div>
    </footer>
  );
}
