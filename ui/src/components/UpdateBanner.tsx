import { useEffect, useState } from "react";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";

import { isTauri } from "../rpc";
import { Spinner } from "./Spinner";

type Phase = "idle" | "available" | "downloading" | "ready" | "failed";

/**
 * In-app updates.
 *
 * Checked once on launch and never enforced: an update that interrupts a DJ
 * mid-preparation is worse than one that waits. Nothing is downloaded until the
 * user asks, and the app only restarts on their say-so.
 */
export function UpdateBanner() {
  const [update, setUpdate] = useState<Update | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!isTauri()) return;
    check()
      .then((found) => {
        if (found) {
          setUpdate(found);
          setPhase("available");
        }
      })
      .catch(() => {
        // No network, no release yet, or a private repo: not worth a banner.
      });
  }, []);

  if (!update || dismissed || phase === "idle") return null;

  const install = async () => {
    setPhase("downloading");
    setError(null);
    let total = 0;
    let received = 0;
    try {
      await update.downloadAndInstall((event) => {
        if (event.event === "Started") total = event.data.contentLength ?? 0;
        if (event.event === "Progress") {
          received += event.data.chunkLength;
          if (total > 0) setProgress(Math.round((received / total) * 100));
        }
      });
      setPhase("ready");
    } catch (cause) {
      setPhase("failed");
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  return (
    <div className="banner info update-banner">
      {phase === "available" && (
        <>
          <span>
            <strong>Version {update.version}</strong> is available.
            {update.body ? ` ${update.body.split("\n")[0]}` : ""}
          </span>
          <span className="wantlist-actions">
            <button className="chip" onClick={() => void install()}>
              update now
            </button>
            <button className="link" onClick={() => setDismissed(true)}>
              later
            </button>
          </span>
        </>
      )}

      {phase === "downloading" && (
        <span>
          <Spinner size={12} label={progress ? `Downloading ${progress}%` : "Downloading…"} />
        </span>
      )}

      {phase === "ready" && (
        <>
          <span>Update installed. Restart to use it.</span>
          <span className="wantlist-actions">
            <button className="chip" onClick={() => void relaunch()}>
              restart now
            </button>
            <button className="link" onClick={() => setDismissed(true)}>
              later
            </button>
          </span>
        </>
      )}

      {phase === "failed" && (
        <>
          <span className="wantlist-error">Update failed: {error}</span>
          <button className="link" onClick={() => setDismissed(true)}>
            dismiss
          </button>
        </>
      )}
    </div>
  );
}
