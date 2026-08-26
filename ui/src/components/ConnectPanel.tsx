import { useState } from "react";
import { openUrl } from "@tauri-apps/plugin-opener";

import { copyText } from "../clipboard";
import { isTauri } from "../rpc";
import { Spinner } from "./Spinner";

const DASHBOARD = "https://developer.spotify.com/dashboard";
export const REDIRECT_URI = "http://127.0.0.1:8888/callback";

interface Props {
  clientId: string;
  busy: boolean;
  onSaveClientId: (clientId: string) => void;
  onConnect: () => void;
}

/**
 * First run.
 *
 * Spotify requires every application to be registered, so there is no way to
 * skip this: the login page has to be told which app is asking. Nothing is
 * baked into the build, because these builds are shared publicly and a bundled
 * Client ID would put one person's Spotify quota behind everyone's usage.
 *
 * The setup is three minutes of clicking, so the steps are here rather than in
 * a README nobody opens — including the exact redirect URI, which is the field
 * people get wrong.
 */
export function ConnectPanel({ clientId, busy, onSaveClientId, onConnect }: Props) {
  const [draft, setDraft] = useState(clientId);
  const [copied, setCopied] = useState(false);

  const ready = draft.trim().length > 0;

  const copyRedirect = async () => {
    const ok = await copyText(REDIRECT_URI);
    setCopied(ok);
    window.setTimeout(() => setCopied(false), 1600);
  };

  if (clientId) {
    return (
      <section className="connect">
        <div className="connect-card">
          <h1>Sync Spotify to rekordbox</h1>
          <p>
            Pick your Spotify playlists, match them against the tracks already in your
            rekordbox collection, and see exactly what you are missing.
          </p>
          <button className="primary big" disabled={busy} onClick={onConnect}>
            {busy ? <Spinner size={14} label="Waiting for Spotify…" /> : "Sign in with Spotify"}
          </button>
          <p className="hint">
            Opens Spotify in your browser. Nothing is written to rekordbox until you review
            a plan and press Apply.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="connect">
      <div className="connect-card setup">
        <h1>Connect Spotify</h1>
        <p>
          Spotify requires every app to be registered, so the login page knows which app is
          asking. You create a free one — it takes about three minutes, once.
        </p>

        <ol className="steps">
          <li>
            <span>Open the Spotify developer dashboard and log in.</span>
            <button
              className="chip"
              onClick={() => {
                if (isTauri()) void openUrl(DASHBOARD);
                else window.open(DASHBOARD, "_blank");
              }}
            >
              open dashboard
            </button>
          </li>
          <li>
            <span>
              Click <strong>Create app</strong>. Name and description can be anything.
            </span>
          </li>
          <li>
            <span>
              Paste this exact <strong>Redirect URI</strong> and press Add:
              <code className="redirect">{REDIRECT_URI}</code>
              Use <code>127.0.0.1</code>, not <code>localhost</code> — Spotify rejects it.
            </span>
            <button className="chip" onClick={() => void copyRedirect()}>
              {copied ? "copied" : "copy"}
            </button>
          </li>
          <li>
            <span>
              Tick <strong>Web API</strong>, accept the terms, save.
            </span>
          </li>
          <li>
            <span>
              Open <strong>Settings</strong> on the app page and copy the{" "}
              <strong>Client ID</strong>. Ignore the Client secret — this app never uses it,
              and you should not share it.
            </span>
          </li>
        </ol>

        <label className="setup-field">
          <span>Client ID</span>
          <input
            className="field"
            placeholder="e.g. 4f2a9c1e8b7d4a3f9e0c1b2a3d4e5f60"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && ready) onSaveClientId(draft.trim());
            }}
          />
        </label>

        <button
          className="primary big"
          disabled={!ready || busy}
          onClick={() => onSaveClientId(draft.trim())}
        >
          {busy ? <Spinner size={14} label="Saving…" /> : "Save and continue"}
        </button>

        <p className="hint">
          A Client ID identifies the app, not you. It is not a secret — it appears in the
          address bar of every Spotify login. You still sign in on Spotify's own page and
          this app never sees your password.
        </p>
      </div>
    </section>
  );
}
