import { open } from "@tauri-apps/plugin-dialog";
import { useState } from "react";
import { useDownloads } from "../downloads";
import { isTauri } from "../rpc";
import type { Settings } from "../types";

type SettingsPatch = Partial<Settings> & { downloaderClientSecret?: string };

interface Props {
  settings: Settings;
  authenticated: boolean;
  onSave: (patch: SettingsPatch) => void | Promise<void>;
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
  const [tagFeatures, setTagFeatures] = useState(settings.tagFeaturesOnSync ?? true);

  const [dlEnabled, setDlEnabled] = useState(settings.downloaderEnabled ?? false);
  const [dlFolder, setDlFolder] = useState(settings.downloadFolder ?? "");
  const [dlClientId, setDlClientId] = useState(settings.downloaderClientId ?? "");
  const [dlSecret, setDlSecret] = useState("");
  const [spotdlPath, setSpotdlPath] = useState(settings.spotdlPath ?? "");
  const { status, refreshStatus, installState, install, cancel } = useDownloads([], {
    enabled: dlEnabled,
  });
  const installing = installState.state === "downloading";

  // Applies at once rather than on Save: switching on may need to fetch spotDL.
  const toggleDownloads = async (enabled: boolean) => {
    setDlEnabled(enabled);
    // Switching off stops what is queued or running, too.
    if (!enabled) await cancel().catch(() => {});
    await onSave({ downloaderEnabled: enabled });
    if (!enabled) return;
    const current = status ?? (await refreshStatus().catch(() => null));
    if (current && (!current.spotdl.path || !current.ffmpeg)) {
      await install().catch(() => {});
    }
  };

  const chooseFolder = async () => {
    const picked = await open({ directory: true, defaultPath: dlFolder || undefined });
    if (typeof picked === "string") setDlFolder(picked);
  };

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
          <h3>Importing</h3>
          <label>
            <input
              type="checkbox"
              checked={tagFeatures}
              onChange={(event) => setTagFeatures(event.target.checked)}
            />
            Tag energy, dance and mood when importing
          </label>
          <p className="hint">
            Writes <code>Energy N</code>, <code>Dance N</code> and <code>Mood N</code> My Tags
            (1–10) on every matched track, in a My Tag column called <code>Vibe</code>. Only
            values rbsync already has are used; nothing extra is looked up.
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

        <section>
          <h3>Downloads</h3>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={dlEnabled}
              disabled={installing}
              title={installing ? "Installing spotDL…" : undefined}
              onChange={(event) => void toggleDownloads(event.target.checked)}
            />
            Download missing tracks (spotDL)
          </label>
          <p className="hint">
            Downloads come from YouTube Music: Opus at about 130–160 kbps, converted to an mp3
            bitrate that matches it and labelled lowq. Fine for practice and emergencies;
            buy the track for club use.
          </p>
          {installing && <p className="hint">Installing spotDL…</p>}
          {installState.state === "failed" && (
            <p className="hint warn">
              Installing spotDL failed{installState.message ? `: ${installState.message}` : "."}
            </p>
          )}
          {status && (
            <p className="hint">
              {status.spotdl.path
                ? `spotDL ${status.version} — ${status.spotdl.path} (${status.spotdl.source})`
                : "spotDL not installed"}
              <br />
              {status.ffmpeg ? `ffmpeg ${status.ffmpeg}` : "ffmpeg not found"}
              {dlEnabled && status.reason ? (
                <>
                  <br />
                  {status.reason}
                </>
              ) : null}
            </p>
          )}
          <div className="row">
            <input
              className="field"
              placeholder="Download folder"
              value={dlFolder}
              onChange={(event) => setDlFolder(event.target.value)}
            />
            {isTauri() && (
              <button className="ghost" onClick={() => void chooseFolder()}>
                Choose…
              </button>
            )}
          </div>
          <input
            className="field"
            placeholder="spotDL client ID (optional)"
            value={dlClientId}
            onChange={(event) => setDlClientId(event.target.value)}
          />
          <div className="row">
            <input
              className="field"
              type="password"
              placeholder={
                settings.hasDownloaderSecret
                  ? "saved"
                  : "spotDL client secret (optional)"
              }
              value={dlSecret}
              onChange={(event) => setDlSecret(event.target.value)}
            />
            {settings.hasDownloaderSecret && (
              <button
                className="ghost"
                onClick={() => void onSave({ downloaderClientSecret: "" })}
              >
                Clear
              </button>
            )}
          </div>
          <input
            className="field"
            placeholder="spotDL path (optional)"
            value={spotdlPath}
            onChange={(event) => setSpotdlPath(event.target.value)}
          />
        </section>

        <div className="modal-actions">
          <button className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="primary"
            onClick={() => {
              onSave({
                clientId,
                autoAccept,
                reject,
                allowRemovals,
                onlySyncable,
                tagFeaturesOnSync: tagFeatures,
                downloaderEnabled: dlEnabled,
                downloadFolder: dlFolder,
                downloaderClientId: dlClientId,
                spotdlPath,
                ...(dlSecret ? { downloaderClientSecret: dlSecret } : {}),
              });
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
