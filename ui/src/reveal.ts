import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { isTauri } from "./rpc";

/** Show a file in Finder / Explorer. No-op outside the desktop app. */
export async function revealPath(path: string): Promise<boolean> {
  if (!isTauri() || !path) return false;
  try {
    await revealItemInDir(path);
    return true;
  } catch {
    return false;
  }
}
