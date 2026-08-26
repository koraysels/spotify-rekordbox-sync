import { writeText } from "@tauri-apps/plugin-clipboard-manager";
import { isTauri } from "./rpc";

/**
 * Copy text to the clipboard.
 *
 * Three paths, in order of preference:
 *  1. Tauri's clipboard plugin — the packaged app, always permitted.
 *  2. The async Clipboard API — modern browsers, but it rejects with
 *     NotAllowedError when the page lacks clipboard permission.
 *  3. A hidden textarea plus `execCommand("copy")` — deprecated, but it is the
 *     only thing that works when permission for (2) is denied.
 *
 * Returns whether the text actually made it to the clipboard, so callers can
 * tell the user when it did not instead of failing silently.
 */
export async function copyText(text: string): Promise<boolean> {
  if (!text) return false;

  if (isTauri()) {
    try {
      await writeText(text);
      return true;
    } catch {
      // Fall through to the browser paths.
    }
  }

  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return legacyCopy(text);
  }
}

function legacyCopy(text: string): boolean {
  try {
    const field = document.createElement("textarea");
    field.value = text;
    // Keep it out of view and out of the layout, but still selectable.
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.top = "-1000px";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    const copied = document.execCommand("copy");
    document.body.removeChild(field);
    return copied;
  } catch {
    return false;
  }
}

/** What to paste into a search box: "Artist - Title". */
export function searchQueryFor(track: { artists: string[]; name: string }): string {
  return `${track.artists.join(", ")} - ${track.name}`.trim().replace(/^-\s*/, "");
}
