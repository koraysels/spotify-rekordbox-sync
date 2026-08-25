import { useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";

import "./App.css";
import { rpc } from "./rpc";
import { Banner } from "./components/Banner";
import { BottomBar } from "./components/BottomBar";
import { PlaylistList } from "./components/PlaylistList";
import { HistoryPanel } from "./components/HistoryPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { StatusBar } from "./components/StatusBar";
import { TrackTable, type BandFilter } from "./components/TrackTable";
import type {
  ApplyResult,
  Playlist,
  PlaylistPlan,
  Settings,
  Status,
  SyncPlan,
  TrackPlan,
} from "./types";

const CALLBACK_PORT = 8888;
const REDIRECT_URI = `http://127.0.0.1:${CALLBACK_PORT}/callback`;
const CLOUD_SYNC_DISMISSED = "rbsync.cloudSyncWarningDismissed";

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [plans, setPlans] = useState<Map<string, PlaylistPlan>>(new Map());
  const [activePlaylist, setActivePlaylist] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<SyncPlan["coverage"] | null>(null);

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const [bandFilter, setBandFilter] = useState<BandFilter>("all");
  const [rowSelection, setRowSelection] = useState<Set<string>>(new Set());
  const [lastClicked, setLastClicked] = useState<string | null>(null);
  const [playlistFilter, setPlaylistFilter] = useState("");
  const [cloudWarning, setCloudWarning] = useState(
    () => localStorage.getItem(CLOUD_SYNC_DISMISSED) !== "1",
  );

  const refreshStatus = useCallback(async () => {
    setStatus(await rpc.call<Status>("status"));
  }, []);

  const run = useCallback(
    async (label: string, task: () => Promise<void>) => {
      setBusy(label);
      setError(null);
      try {
        await task();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setBusy(null);
        void refreshStatus();
      }
    },
    [refreshStatus],
  );

  useEffect(() => {
    const unsubscribe = rpc.onProgress((message) => setBusy(message));
    void run("Starting", async () => {
      setSettings(await rpc.call<Settings>("settings.get"));
      const current = await rpc.call<Status>("status");
      setStatus(current);
      setSelected(new Set(current.selected_playlists));
    });
    return unsubscribe;
  }, [run]);

  const loadPlaylists = useCallback(
    () =>
      run("Loading playlists", async () => {
        const result = await rpc.call<{ playlists: Playlist[] }>("playlists.list");
        setPlaylists(result.playlists);
      }),
    [run],
  );

  useEffect(() => {
    if (status?.authenticated && playlists.length === 0) void loadPlaylists();
  }, [status?.authenticated, playlists.length, loadPlaylists]);

  const persistSelection = useCallback(
    (next: Set<string>) => {
      setSelected(next);
      void rpc.call("playlists.setSelected", { playlistIds: [...next] });
    },
    [],
  );

  const togglePlaylist = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    persistSelection(next);
  };

  const connectSpotify = () =>
    run("Waiting for Spotify sign-in", async () => {
      const { url } = await rpc.call<{ url: string }>("auth.begin", {
        redirectUri: REDIRECT_URI,
      });
      // Start listening before opening the browser, so a fast redirect is not missed.
      const codePromise = invoke<string>("oauth_listen", {
        port: CALLBACK_PORT,
        timeoutSecs: 300,
      });
      await openUrl(url);
      const code = await codePromise;
      await rpc.call("auth.complete", { code, redirectUri: REDIRECT_URI });
      setNotice("Connected to Spotify.");
      await loadPlaylists();
    });

  const disconnectSpotify = () =>
    run("Disconnecting", async () => {
      await rpc.call("auth.clear");
      setPlaylists([]);
    });

  const saveSettings = (patch: Partial<Settings>) =>
    run("Saving settings", async () => {
      setSettings(await rpc.call<Settings>("settings.set", patch as Record<string, unknown>));
    });

  const planSync = () =>
    run("Planning", async () => {
      if (!status?.tracks_indexed) await rpc.call("library.load");
      const plan = await rpc.call<SyncPlan>("sync.plan", { playlistIds: [...selected] });
      const map = new Map<string, PlaylistPlan>();
      plan.playlists.forEach((entry) => map.set(entry.playlist.id, entry));
      setPlans(map);
      setCoverage(plan.coverage);
      setActivePlaylist(plan.playlists[0]?.playlist.id ?? null);
      setRowSelection(new Set());
    });

  const applySync = () =>
    run("Writing to rekordbox", async () => {
      const result = await rpc.call<{ results: ApplyResult[] }>("sync.apply");
      const added = result.results.reduce((sum, entry) => sum + entry.added, 0);
      const removed = result.results.reduce((sum, entry) => sum + entry.removed, 0);
      setNotice(
        `Wrote ${added} track(s)${removed ? `, removed ${removed}` : ""} to rekordbox. ` +
          `Backup: ${result.results[0]?.backupPath ?? "none"}`,
      );
      setPlans(new Map());
      setCoverage(null);
    });

  const exportWantlist = () =>
    run("Exporting", async () => {
      const result = await rpc.call<{ path: string }>("wantlist.export");
      setNotice(`Wantlist written to ${result.path}`);
    });

  const decide = (tracks: TrackPlan[], accepted: boolean) =>
    run(accepted ? "Accepting matches" : "Rejecting matches", async () => {
      const decisions = tracks
        .filter((entry) => entry.candidates.length > 0 || !accepted)
        .map((entry) => ({
          spotify_id: entry.track.id,
          content_id: entry.candidates[0]?.contentId ?? "",
          accepted,
        }));
      if (decisions.length === 0) return;
      await rpc.call("review.decide", { decisions });
      // Re-plan so the preview reflects the decisions that were just made.
      const plan = await rpc.call<SyncPlan>("sync.plan", { playlistIds: [...selected] });
      const map = new Map<string, PlaylistPlan>();
      plan.playlists.forEach((entry) => map.set(entry.playlist.id, entry));
      setPlans(map);
      setCoverage(plan.coverage);
      setRowSelection(new Set());
    });

  const activePlan = useMemo(
    () => (activePlaylist ? plans.get(activePlaylist) ?? null : null),
    [activePlaylist, plans],
  );

  const needsSetup = settings !== null && !settings.clientId;

  return (
    <div className="app">
      <StatusBar
        status={status}
        busy={busy}
        onSettings={() => setShowSettings(true)}
        onHistory={() => setShowHistory(true)}
      />

      {cloudWarning && (
        <Banner
          tone="warn"
          message="If rekordbox Cloud Library Sync is enabled, turn it off before writing. Cloud sync can revert or duplicate playlists written by other tools."
          onDismiss={() => {
            localStorage.setItem(CLOUD_SYNC_DISMISSED, "1");
            setCloudWarning(false);
          }}
        />
      )}
      {needsSetup && (
        <Banner tone="info" message="Add your Spotify Client ID in Settings to get started." />
      )}
      {status?.rekordbox_running && (
        <Banner tone="warn" message="Rekordbox is running. Quit it completely before applying changes." />
      )}
      {error && <Banner tone="error" message={error} onDismiss={() => setError(null)} />}
      {notice && <Banner tone="info" message={notice} onDismiss={() => setNotice(null)} />}

      <main className="main">
        <PlaylistList
          playlists={playlists}
          selected={selected}
          active={activePlaylist}
          plans={plans}
          onToggle={togglePlaylist}
          onActivate={setActivePlaylist}
          onSelectAll={() => persistSelection(new Set(playlists.map((p) => p.id)))}
          onSelectNone={() => persistSelection(new Set())}
          filter={playlistFilter}
          onFilter={setPlaylistFilter}
        />
        <TrackTable
          plan={activePlan}
          filter={bandFilter}
          onFilter={setBandFilter}
          selectedIds={rowSelection}
          onSelect={setRowSelection}
          onDecide={decide}
          lastClicked={lastClicked}
          onLastClicked={setLastClicked}
        />
      </main>

      <BottomBar
        selectedCount={selected.size}
        coverage={coverage}
        hasPlan={plans.size > 0}
        rekordboxRunning={Boolean(status?.rekordbox_running)}
        busy={busy !== null}
        onPlan={planSync}
        onApply={applySync}
        onExport={exportWantlist}
      />

      {showHistory && <HistoryPanel onClose={() => setShowHistory(false)} />}

      {showSettings && settings && (
        <SettingsPanel
          settings={settings}
          authenticated={Boolean(status?.authenticated)}
          onSave={saveSettings}
          onConnect={connectSpotify}
          onDisconnect={disconnectSpotify}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
  );
}
