import { WebviewWindow } from "@tauri-apps/api/webviewWindow";

import { isTauri } from "./rpc";

const LABEL = "sync";

/**
 * Open the Sync view as a real window.
 *
 * A separate window rather than an overlay: it is a working surface you keep
 * beside the track list, and as its own window the OS handles stacking, so
 * nothing has to fight a z-index.
 */
export async function openSyncWindow(): Promise<void> {
  if (!isTauri()) {
    window.open(`${window.location.pathname}?view=sync`, "_blank");
    return;
  }

  const existing = await WebviewWindow.getByLabel(LABEL);
  if (existing) {
    await existing.setFocus();
    return;
  }

  const created = new WebviewWindow(LABEL, {
    url: `index.html?view=sync`,
    title: "Sync — Spotify to rekordbox",
    width: 1040,
    height: 700,
    minWidth: 820,
    minHeight: 520,
    resizable: true,
  });

  created.once("tauri://error", (event) => {
    console.error("could not open the sync window", event);
  });
}
