import { useState } from "react";
import { revealItemInDir } from "@tauri-apps/plugin-opener";

import { copyText } from "../clipboard";
import { isTauri } from "../rpc";

interface Props {
  path: string;
  text: string;
  count: number;
  onDismiss: () => void;
}

/**
 * Shown after exporting the wantlist.
 *
 * A file path alone is not much use — the two things anyone actually wants next
 * are the list itself on the clipboard, or the file in front of them.
 */
export function WantlistBanner({ path, text, count, onDismiss }: Props) {
  const [copied, setCopied] = useState<boolean | null>(null);
  const [revealError, setRevealError] = useState<string | null>(null);

  const copy = async () => {
    const ok = await copyText(text);
    setCopied(ok);
    window.setTimeout(() => setCopied(null), 1500);
  };

  const reveal = async () => {
    if (!isTauri()) {
      setRevealError("Opening Finder needs the desktop app.");
      window.setTimeout(() => setRevealError(null), 2500);
      return;
    }
    try {
      await revealItemInDir(path);
    } catch (cause) {
      setRevealError(cause instanceof Error ? cause.message : String(cause));
      window.setTimeout(() => setRevealError(null), 2500);
    }
  };

  return (
    <div className="banner info wantlist-banner">
      <span className="wantlist-text">
        {count} missing track{count === 1 ? "" : "s"} written to <code>{path}</code>
        {revealError && <span className="wantlist-error"> — {revealError}</span>}
      </span>
      <span className="wantlist-actions">
        <button className="chip" onClick={copy} disabled={!text} data-tip="Copy the whole list as text">
          {copied === null ? "copy list" : copied ? "copied" : "failed"}
        </button>
        <button className="chip" onClick={reveal} data-tip="Show the file in Finder">
          show in Finder
        </button>
        <button className="link" onClick={onDismiss}>
          dismiss
        </button>
      </span>
    </div>
  );
}
