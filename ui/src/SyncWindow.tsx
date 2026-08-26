import { useCallback, useEffect, useState } from "react";

import "./App.css";
import { ApplyDialog, type ApplyState } from "./components/ApplyDialog";
import { Banner } from "./components/Banner";
import { SyncView } from "./components/SyncView";
import { callViaMainWindow, onMainWindowProgress } from "./bridge";
import { revealPath } from "./reveal";
import type { ApplyResult, Playlist, PlaylistPlan, Status, SyncPlan } from "./types";

/**
 * The Sync window: a real OS window, not an overlay.
 *
 * It keeps no shared state with the main window — everything it needs comes
 * from the core over the bridge — so the two cannot disagree. Its progress and
 * result dialogs live here, which is why they can never end up hidden behind
 * it.
 */
export default function SyncWindow() {
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [plans, setPlans] = useState<Map<string, PlaylistPlan>>(new Map());
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applyState, setApplyState] = useState<ApplyState | null>(null);
  const [libraryVersion, setLibraryVersion] = useState(0);

  const refresh = useCallback(async () => {
    const [current, listed] = await Promise.all([
      callViaMainWindow<Status>("status"),
      callViaMainWindow<{ playlists: Playlist[] }>("playlists.cached"),
    ]);
    setStatus(current);
    setPlaylists(listed.playlists);
    setSelected(new Set(current.selected_playlists));

    if (current.selected_playlists.length > 0) {
      const cached = await callViaMainWindow<{ playlists: PlaylistPlan[] }>("plans.cached", {
        playlistIds: current.selected_playlists,
      });
      const map = new Map<string, PlaylistPlan>();
      cached.playlists.forEach((entry) => map.set(entry.playlist.id, entry));
      setPlans(map);
    }
  }, []);

  useEffect(() => {
    void refresh().catch((cause) =>
      setError(cause instanceof Error ? cause.message : String(cause)),
    );
    return onMainWindowProgress((message) => setBusy(message));
  }, [refresh]);

  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
    void callViaMainWindow("playlists.setSelected", { playlistIds: [...next] });
  };

  const persist = (ids: Set<string>) => {
    setSelected(ids);
    void callViaMainWindow("playlists.setSelected", { playlistIds: [...ids] });
  };

  const plan = async () => {
    setBusy("Planning");
    setError(null);
    try {
      if (!status?.tracks_indexed) await callViaMainWindow("library.load");
      const result = await callViaMainWindow<SyncPlan>("sync.plan", {
        playlistIds: [...selected],
        force: true,
      });
      const map = new Map<string, PlaylistPlan>();
      result.playlists.forEach((entry) => map.set(entry.playlist.id, entry));
      setPlans(map);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  const apply = async () => {
    setApplyState({ phase: "running", message: "Checking that rekordbox is closed", results: [], error: null });
    setBusy("Writing to rekordbox");
    try {
      const result = await callViaMainWindow<{ results: ApplyResult[] }>("sync.apply");
      setApplyState({ phase: "done", message: "", results: result.results, error: null });
      setPlans(new Map());
      setLibraryVersion((current) => current + 1);
      void refresh();
    } catch (cause) {
      setApplyState({
        phase: "error",
        message: "",
        results: [],
        error: cause instanceof Error ? cause.message : String(cause),
      });
    } finally {
      // Progress events only ever set the message; without this the button
      // stays on "Working…" forever once the last event has arrived.
      setBusy(null);
    }
  };

  return (
    <div className="app syncwindow">
      {error && <Banner tone="error" message={error} onDismiss={() => setError(null)} />}
      {status?.rekordbox_running && (
        <Banner tone="warn" message="Rekordbox is running. Quit it before applying." />
      )}

      <SyncView
        playlists={playlists}
        selected={selected}
        plans={plans}
        busy={busy !== null}
        rekordboxRunning={Boolean(status?.rekordbox_running)}
        hasPlan={plans.size > 0}
        onToggle={toggle}
        onSelectAll={() => persist(new Set(playlists.map((p) => p.id)))}
        onSelectNone={() => persist(new Set())}
        onPlan={plan}
        onApply={apply}
        refreshKey={libraryVersion}
      />

      {applyState && (
        <ApplyDialog
          state={applyState}
          onClose={() => setApplyState(null)}
          onReveal={(path) => void revealPath(path)}
        />
      )}
    </div>
  );
}
