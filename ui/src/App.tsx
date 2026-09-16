import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";

import "./App.css";
import { isTauri, rpc } from "./rpc";
import { openSyncWindow } from "./syncWindow";
import { serveRpcToOtherWindows } from "./bridge";
import { revealPath } from "./reveal";
import { Banner } from "./components/Banner";
import { BottomBar } from "./components/BottomBar";
import { ApplyDialog, type ApplyState } from "./components/ApplyDialog";
import { BackupsPanel } from "./components/BackupsPanel";
import { CandidatePicker } from "./components/CandidatePicker";
import { ConnectPanel } from "./components/ConnectPanel";
import { PlaylistList } from "./components/PlaylistList";
import { HistoryPanel } from "./components/HistoryPanel";
import { RekordboxPanel } from "./components/RekordboxPanel";
import { EnergyPanel } from "./components/EnergyPanel";
import { DecisionsPanel } from "./components/DecisionsPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { StatusBar } from "./components/StatusBar";
import { UpdateBanner } from "./components/UpdateBanner";
import { WantlistBanner } from "./components/WantlistBanner";
import type { TrackFeatures } from "./types";
import {
  TrackTable,
  type BandFilter,
  type BrowseState,
  type FileStatus,
} from "./components/TrackTable";
import type {
  CachedPlans,
  Playlist,
  SpotifyTrack,
  PlaylistPlan,
  Settings,
  Status,
  SyncPlan,
  TrackPlan,
} from "./types";

const CALLBACK_PORT = 8888;
const REDIRECT_URI = `http://127.0.0.1:${CALLBACK_PORT}/callback`;
const CLOUD_SYNC_DISMISSED = "rbsync.cloudSyncWarningDismissed";
/** Tracks per audio-feature request. Small enough that other RPC calls get a turn. */
const FEATURE_CHUNK = 100;

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
  const [showLibrary, setShowLibrary] = useState(false);
  const [showBackups, setShowBackups] = useState(false);
  const [showEnergy, setShowEnergy] = useState(false);
  const [showDecisions, setShowDecisions] = useState(false);
  const [features, setFeatures] = useState<Map<string, TrackFeatures>>(new Map());
  // Read inside the fetch loop without making it a dependency, or every arriving
  // chunk would restart the loop.
  const featuresRef = useRef(features);
  featuresRef.current = features;
  // Bumped after an Apply so the rekordbox column re-reads the database.
  const [, setLibraryVersion] = useState(0);
  const [applyState, setApplyState] = useState<ApplyState | null>(null);
  const [files, setFiles] = useState<Map<string, FileStatus>>(new Map());
  const [picking, setPicking] = useState<TrackPlan | null>(null);
  const [staleIds, setStaleIds] = useState<Set<string>>(new Set());
  const [wantlist, setWantlist] = useState<
    { path: string; text: string; count: number } | null
  >(null);
  const [browse, setBrowse] = useState<Map<string, BrowseState>>(new Map());

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
    void serveRpcToOtherWindows();
  }, []);

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

  // Paint the sidebar from the last known list, then let the live fetch above
  // replace it. Purely a first paint: nothing is synced from this.
  useEffect(() => {
    if (!status?.authenticated || playlists.length > 0) return;
    void rpc
      .call<{ playlists: Playlist[] }>("playlists.cached")
      .then((result) => {
        if (result.playlists.length === 0) return;
        setPlaylists((current) => (current.length === 0 ? result.playlists : current));
      })
      .catch(() => {
        // No cached list is a normal first run.
      });
  }, [status?.authenticated, playlists.length]);

  useEffect(() => {
    if (status?.authenticated && playlists.length === 0) void loadPlaylists();
  }, [status?.authenticated, playlists.length, loadPlaylists]);

  const restoredFor = useRef<string | null>(null);

  // Show the last computed plan immediately on launch, rather than making the
  // user re-plan. Anything that changed since is flagged rather than hidden.
  useEffect(() => {
    if (playlists.length === 0 || selected.size === 0) return;
    const key = [...selected].sort().join(",");
    if (restoredFor.current === key) return;
    restoredFor.current = key;

    void (async () => {
      try {
        const result = await rpc.call<CachedPlans>("plans.cached", {
          playlistIds: [...selected],
        });
        if (result.playlists.length === 0) return;

        const map = new Map<string, PlaylistPlan>();
        result.playlists.forEach((entry) => map.set(entry.playlist.id, entry));
        setPlans(map);
        setCoverage(result.coverage);
        setActivePlaylist((current) => current ?? result.playlists[0].playlist.id);

        const byId = new Map(playlists.map((p) => [p.id, p]));
        const stale = new Set<string>();
        for (const [playlistId, info] of Object.entries(result.stored ?? {})) {
          const live = byId.get(playlistId);
          if (!info.fingerprintMatches || (live && live.snapshotId !== info.snapshotId)) {
            stale.add(playlistId);
          }
        }
        setStaleIds(stale);
      } catch {
        // A missing or unreadable stored plan is not worth surfacing.
      }
    })();
  }, [playlists, selected]);

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
      if (!isTauri()) {
        // The OAuth redirect is caught by a loopback listener in the Rust
        // shell, which does not exist when the UI runs in a plain browser.
        throw new Error(
          "Signing in needs the desktop app — the browser dev server cannot " +
            "receive Spotify's redirect. Sign in from rbsync.app instead.",
        );
      }
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

  const saveSettings = (patch: Partial<Settings>): Promise<void> =>
    run("Saving settings", async () => {
      const updated = await rpc.call<Settings>(
        "settings.set",
        patch as Record<string, unknown>,
      );
      setSettings(updated);
      // The visible playlist set depends on this setting, so refresh it.
      if (patch.onlySyncable !== undefined && status?.authenticated) {
        const result = await rpc.call<{ playlists: Playlist[] }>("playlists.list");
        setPlaylists(result.playlists);
      }
    });

  const planSync = () =>
    run("Planning", async () => {
      // Always re-read the collection: files imported into rekordbox since the
      // last read would otherwise never be matched until the app restarts.
      await rpc.call("library.load");
      const plan = await rpc.call<SyncPlan>("sync.plan", {
        playlistIds: [...selected],
        force: true,
      });
      const map = new Map<string, PlaylistPlan>();
      plan.playlists.forEach((entry) => map.set(entry.playlist.id, entry));
      setPlans(map);
      setCoverage(plan.coverage);
      // Stay on the playlist being looked at; jumping to the first one loses
      // your place every time you re-plan.
      setActivePlaylist((current) =>
        current && map.has(current) ? current : plan.playlists[0]?.playlist.id ?? null,
      );
      setRowSelection(new Set());
      setStaleIds(new Set());
    });

  const exportWantlist = () =>
    run("Exporting", async () => {
      const result = await rpc.call<{ path: string; paths: string[] }>("wantlist.export");
      const contents = await rpc.call<{ rows: unknown[]; text: string }>("wantlist.get");
      setWantlist({
        // Prefer the plain-text export for "show in Finder"; it is the one
        // people paste into a search tool.
        path: result.paths?.find((p) => p.endsWith(".txt")) ?? result.path,
        text: contents.text,
        count: contents.rows.length,
      });
    });

  const replan = useCallback(async () => {
    const plan = await rpc.call<SyncPlan>("sync.plan", { playlistIds: [...selected] });
    const map = new Map<string, PlaylistPlan>();
    plan.playlists.forEach((entry) => map.set(entry.playlist.id, entry));
    setPlans(map);
    setCoverage(plan.coverage);
  }, [selected]);

  const chooseCandidate = (row: TrackPlan, contentId: string | null) =>
    run(contentId ? "Saving match" : "Marking as missing", async () => {
      await rpc.call("review.decide", {
        decisions: [
          {
            spotify_id: row.track.id,
            content_id: contentId ?? "",
            accepted: Boolean(contentId),
            ...decisionContext(row, contentId),
          },
        ],
      });
      setPicking(null);
      await replan();
    });

  const decide = (tracks: TrackPlan[], accepted: boolean) =>
    run(accepted ? "Accepting matches" : "Rejecting matches", async () => {
      const decisions = tracks
        .filter((entry) => entry.candidates.length > 0 || !accepted)
        .map((entry) => ({
          spotify_id: entry.track.id,
          content_id: entry.candidates[0]?.contentId ?? "",
          accepted,
          ...decisionContext(entry, entry.candidates[0]?.contentId ?? null),
        }));
      if (decisions.length === 0) return;
      await rpc.call("review.decide", { decisions });
      // Re-plan so the preview reflects the decisions that were just made.
      await replan();
      setRowSelection(new Set());
    });

  /**
   * Names stored with a decision, so it can be understood and undone later.
   * Two bare ids cannot say which song was rejected, or which file.
   */
  const decisionContext = (row: TrackPlan, contentId: string | null) => ({
    track_display: row.track.display,
    content_display: row.candidates.find((c) => c.contentId === contentId)?.display ?? "",
    playlist_name: activePlan?.playlist.name ?? "",
  });

  const undoDecision = (row: TrackPlan) =>
    run("Undoing decision", async () => {
      await rpc.call("decisions.forget", { spotifyIds: [row.track.id] });
      await replan();
    });

  const openPlaylist = useCallback(
    (playlistId: string) => {
      setActivePlaylist(playlistId);
      if (plans.has(playlistId) || browse.has(playlistId)) return;

      setBrowse((current) =>
        new Map(current).set(playlistId, { tracks: [], error: null, loading: true }),
      );
      rpc
        .call<{ tracks: SpotifyTrack[]; error: string | null }>("playlists.tracks", {
          playlistId,
        })
        .then((result) =>
          setBrowse((current) =>
            new Map(current).set(playlistId, {
              tracks: result.tracks,
              error: result.error,
              loading: false,
            }),
          ),
        )
        .catch((cause) =>
          setBrowse((current) =>
            new Map(current).set(playlistId, {
              tracks: [],
              error: cause instanceof Error ? cause.message : String(cause),
              loading: false,
            }),
          ),
        );
    },
    [plans, browse],
  );

  useEffect(() => {
    const contentIds = [...plans.values()]
      .flatMap((entry) => entry.tracks)
      .map((entry) => entry.contentId)
      .filter((id): id is string => Boolean(id));
    if (contentIds.length === 0) {
      setFiles(new Map());
      return;
    }
    void rpc
      .call<{ files: Record<string, FileStatus> }>("tracks.verify", {
        contentIds: [...new Set(contentIds)],
      })
      .then((result) => setFiles(new Map(Object.entries(result.files))))
      .catch(() => {
        // Verification is advisory; failing to check must not block the plan.
      });
  }, [plans]);

  // Audio features for the playlist being looked at — never for every plan at
  // once. The core answers one request at a time, so a five-thousand-track
  // lookup would block every other action until it finished. Small chunks let
  // planning, exporting and applying keep working while these trickle in.
  useEffect(() => {
    const plan = activePlaylist ? plans.get(activePlaylist) : null;
    if (!plan) return;
    const ids = [...new Set(plan.tracks.map((t) => t.track.id))].filter(
      (id) => id && !featuresRef.current.has(id),
    );
    if (ids.length === 0) return;

    let cancelled = false;
    void (async () => {
      for (let start = 0; start < ids.length && !cancelled; start += FEATURE_CHUNK) {
        try {
          const result = await rpc.call<{ features: Record<string, TrackFeatures> }>("features.get", {
            spotifyIds: ids.slice(start, start + FEATURE_CHUNK),
          });
          if (cancelled) return;
          setFeatures((current) => new Map([...current, ...Object.entries(result.features)]));
        } catch {
          // Features are extra information; a failed lookup leaves the columns
          // empty rather than interrupting what the user is doing.
          return;
        }
      }
    })();
    // Switching playlist abandons the rest: those tracks are no longer on screen.
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePlaylist, plans]);

  const activePlan = useMemo(
    () => (activePlaylist ? plans.get(activePlaylist) ?? null : null),
    [activePlaylist, plans],
  );

  const connected = Boolean(status?.authenticated);

  return (
    <div className="app">
      <StatusBar
        status={status}
        busy={busy}
        onSettings={() => setShowSettings(true)}
        onHistory={() => setShowHistory(true)}
        onLibrary={() => setShowLibrary(true)}
        onBackups={() => setShowBackups(true)}
        onEnergy={() => setShowEnergy(true)}
        onDecisions={() => setShowDecisions(true)}
      />

      <UpdateBanner />

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
      {status?.rekordbox_running && (
        <Banner tone="warn" message="Rekordbox is running. Quit it completely before applying changes." />
      )}
      {wantlist && (
        <WantlistBanner
          path={wantlist.path}
          text={wantlist.text}
          count={wantlist.count}
          onDismiss={() => setWantlist(null)}
        />
      )}
      {error && <Banner tone="error" message={error} onDismiss={() => setError(null)} />}
      {notice && <Banner tone="info" message={notice} onDismiss={() => setNotice(null)} />}

      {!connected && status !== null ? (
        <ConnectPanel
          clientId={settings?.clientId ?? ""}
          busy={busy !== null}
          onConnect={connectSpotify}
          onSaveClientId={(clientId) => {
            // Saving the id is what unlocks sign-in, so do both in one gesture.
            void saveSettings({ clientId }).then(() => connectSpotify());
          }}
        />
      ) : (
      <main className="main">
        <PlaylistList
          playlists={playlists}
          selected={selected}
          active={activePlaylist}
          plans={plans}
          onToggle={togglePlaylist}
          onActivate={openPlaylist}
          onSelectAll={() => persistSelection(new Set(playlists.map((p) => p.id)))}
          onSelectNone={() => persistSelection(new Set())}
          filter={playlistFilter}
          onFilter={setPlaylistFilter}
          loading={busy !== null}
          onRefresh={() => void loadPlaylists()}
          staleIds={staleIds}
        />
        <TrackTable
          plan={activePlan}
          filter={bandFilter}
          onFilter={setBandFilter}
          selectedIds={rowSelection}
          onSelect={setRowSelection}
          onDecide={decide}
          onInspect={setPicking}
          lastClicked={lastClicked}
          onLastClicked={setLastClicked}
          browse={activePlaylist ? browse.get(activePlaylist) ?? null : null}
          files={files}
          features={features}
          onUndoDecision={(row) => void undoDecision(row)}
        />
      </main>
      )}

      <BottomBar
        onOpenSync={() => void openSyncWindow()}
        selectedCount={selected.size}
        coverage={coverage}
        hasPlan={plans.size > 0}
        busy={busy !== null}
        onPlan={planSync}
        onExport={exportWantlist}
      />


      {showHistory && <HistoryPanel onClose={() => setShowHistory(false)} />}
      {showLibrary && <RekordboxPanel onClose={() => setShowLibrary(false)} />}
      {showDecisions && (
        <DecisionsPanel
          onClose={() => setShowDecisions(false)}
          // Undone decisions change what a plan would do; recompute when
          // there is something selected to plan.
          onChanged={() => {
            if (selected.size > 0) void replan();
          }}
        />
      )}
      {showEnergy && (
        <EnergyPanel
          onClose={() => setShowEnergy(false)}
          rekordboxRunning={Boolean(status?.rekordbox_running)}
        />
      )}
      {showBackups && (
        <BackupsPanel
          onClose={() => setShowBackups(false)}
          onRestored={() => {
            // The library on disk changed, so everything derived from it is stale.
            setPlans(new Map());
            setCoverage(null);
            setFiles(new Map());
            restoredFor.current = null;
            setLibraryVersion((current) => current + 1);
            setNotice("rekordbox library restored from backup.");
            void refreshStatus();
          }}
        />
      )}

      {applyState && (
        <ApplyDialog
          state={applyState}
          onClose={() => setApplyState(null)}
          onReveal={(path) => {
            void revealPath(path);
          }}
        />
      )}

      {picking && (
        <CandidatePicker
          row={picking}
          onChoose={(contentId) => chooseCandidate(picking, contentId)}
          onReject={() => chooseCandidate(picking, null)}
          onClose={() => setPicking(null)}
        />
      )}

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
