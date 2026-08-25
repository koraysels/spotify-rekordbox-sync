interface Props {
  clientIdSet: boolean;
  busy: boolean;
  onConnect: () => void;
  onSettings: () => void;
}

/**
 * First-run screen. Sign-in is one button when the build ships its own Spotify
 * Client ID; supplying your own is an escape hatch, not a prerequisite.
 */
export function ConnectPanel({ clientIdSet, busy, onConnect, onSettings }: Props) {
  return (
    <section className="connect">
      <div className="connect-card">
        <h1>Sync Spotify to rekordbox</h1>
        <p>
          Pick your Spotify playlists, match them against the tracks already in your
          rekordbox collection, and see exactly what you are missing.
        </p>

        {clientIdSet ? (
          <>
            <button className="primary big" disabled={busy} onClick={onConnect}>
              {busy ? "Waiting for Spotify…" : "Sign in with Spotify"}
            </button>
            <p className="hint">
              Opens Spotify in your browser. Nothing is written to rekordbox until you
              review a plan and press Apply.
            </p>
          </>
        ) : (
          <>
            <p className="hint warn">
              This build has no bundled Spotify app, so it needs a Client ID before it can
              sign in.
            </p>
            <button className="primary big" onClick={onSettings}>
              Add a Client ID
            </button>
          </>
        )}
      </div>
    </section>
  );
}
