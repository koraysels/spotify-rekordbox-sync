interface Props {
  /** Size in pixels. Defaults to matching the surrounding text. */
  size?: number;
  label?: string;
}

/**
 * Indeterminate activity indicator.
 *
 * Used wherever the app waits on something it cannot measure — Spotify's OAuth
 * round trip, a playlist fetch. Without it those pauses read as a freeze.
 */
export function Spinner({ size = 13, label }: Props) {
  return (
    <span className="spinner-wrap" role="status" aria-live="polite">
      <span
        className="spinner"
        style={{ width: size, height: size }}
        aria-hidden="true"
      />
      {label && <span className="spinner-label">{label}</span>}
    </span>
  );
}
