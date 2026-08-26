import { useState } from "react";
import type { Settings } from "../types";

interface Props {
  settings: Settings;
  authenticated: boolean;
  onSave: (patch: Partial<Settings>) => void;
  onConnect: () => void;
  onDisconnect: () => void;
  onClose: () => void;
}

export function SettingsPanel({
  settings,
  authenticated,
  onSave,
  onConnect,
  onDisconnect,
  onClose,
}: Props) {
  const [clientId, setClientId] = useState(settings.clientId);
  const [autoAccept, setAutoAccept] = useState(settings.autoAccept);
  const [reject, setReject] = useState(settings.reject);
  const [allowRemovals, setAllowRemovals] = useState(settings.allowRemovals);
  const [onlySyncable, setOnlySyncable] = useState(settings.onlySyncable);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <h2>Settings</h2>

        <section>
          <h3>Spotify</h3>
          <p className="hint">
            Sign-in normally needs no setup. Supply your own Client ID only if you want to
            use your own Spotify app: create one at developer.spotify.com, add{" "}
            <code>http://127.0.0.1:8888/callback</code> as a redirect URI, and paste the
            Client ID below. Leave it empty to use the bundled app.
          </p>
          <input
            className="field"
            placeholder="Spotify Client ID (optional)"
            value={clientId}
            onChange={(event) => setClientId(event.target.value)}
          />
          <div className="row">
            {authenticated ? (
              <button className="ghost" onClick={onDisconnect}>
                Disconnect
              </button>
            ) : (
              <button className="primary" onClick={onConnect} disabled={!clientId}>
                Connect Spotify
              </button>
            )}
          </div>
        </section>

        <section>
          <h3>Playlists</h3>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={onlySyncable}
              onChange={(event) => setOnlySyncable(event.target.checked)}
            />
            Only show playlists I can sync
          </label>
          <p className="hint">
            Spotify only shares the contents of playlists you own or collaborate on.
            Playlists you merely follow cannot be read at all, so they are hidden. Turn
            this off to list them anyway.
          </p>
        </section>

        <section>
          <h3>Matching</h3>
          <label className="slider">
            Auto-accept above
            <input
              type="range"
              min={0.5}
              max={1}
              step={0.01}
              value={autoAccept}
              onChange={(event) => setAutoAccept(Number(event.target.value))}
            />
            <span className="value">{autoAccept.toFixed(2)}</span>
          </label>
          <label className="slider">
            Discard below
            <input
              type="range"
              min={0.1}
              max={0.9}
              step={0.01}
              value={reject}
              onChange={(event) => setReject(Number(event.target.value))}
            />
            <span className="value">{reject.toFixed(2)}</span>
          </label>
          <p className="hint">
            Anything between the two lands in the review queue. Decisions you make there
            are remembered, so each track is only ever asked about once.
          </p>
        </section>

        <section>
          <h3>Removals</h3>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={allowRemovals}
              onChange={(event) => setAllowRemovals(event.target.checked)}
            />
            Remove rekordbox tracks that are no longer in the Spotify playlist
          </label>
          <p className="hint warn">
            Off by default. With this on, tracks you added manually in rekordbox will be
            removed when they are not in the Spotify playlist.
          </p>
        </section>

        <div className="modal-actions">
          <button className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="primary"
            onClick={() => {
              onSave({ clientId, autoAccept, reject, allowRemovals, onlySyncable });
              onClose();
            }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
