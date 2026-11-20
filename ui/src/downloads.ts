import { useCallback, useEffect, useState } from "react";

import { isTauri, rpc } from "./rpc";
import type {
  DownloadJob,
  DownloadRecord,
  DownloaderStatus,
  SpotifyTrack,
} from "./types";

const ACTIVE = new Set(["queued", "downloading", "converting"]);
const POLL_MS = 1500;
const INSTALL_JOB = "install";
const INSTALL_GIVE_UP_MS = 3 * 60 * 1000;

/** Why downloading cannot start yet, or "" when spotDL and ffmpeg are both there. */
export function downloadBlocker(status: DownloaderStatus | null): string {
  if (!status?.spotdl.path) return "Install spotDL in Settings first";
  if (!status.ffmpeg) return "ffmpeg not found: use Install in Settings, or install ffmpeg yourself";
  return "";
}

/** Latest spotDL install progress; `message` carries the failure reason. */
export interface InstallState {
  state: "idle" | "downloading" | "done" | "failed";
  message: string;
}

export interface DownloadsOptions {
  /** False makes no calls at all: the downloader is switched off. */
  enabled?: boolean;
  /** The status is read again whenever this changes (e.g. saved settings). */
  refreshOn?: unknown;
}

/**
 * Download state for a set of tracks.
 *
 * Live job progress arrives as `download.progress` notifications; finished
 * downloads are read back from `downloads.get` so the file's existence is
 * checked on disk. In browser dev mode there is no notification stream, so
 * the status is polled while anything is in flight.
 */
export function useDownloads(
  spotifyIds: string[],
  { enabled = true, refreshOn }: DownloadsOptions = {},
) {
  const [jobs, setJobs] = useState<Map<string, DownloadJob>>(new Map());
  const [records, setRecords] = useState<Map<string, DownloadRecord>>(new Map());
  const [status, setStatus] = useState<DownloaderStatus | null>(null);
  const [installState, setInstallState] = useState<InstallState>({
    state: "idle",
    message: "",
  });

  const idsKey = spotifyIds.join(",");

  const refreshRecords = useCallback(async (ids: string[]) => {
    if (!ids.length) return;
    const found = await rpc.call<Record<string, DownloadRecord>>("downloads.get", {
      spotifyIds: ids,
    });
    setRecords((prev) => {
      const next = new Map(prev);
      for (const [id, record] of Object.entries(found)) next.set(id, record);
      return next;
    });
  }, []);

  const refreshStatus = useCallback(async () => {
    const next = await rpc.call<DownloaderStatus>("downloader.status");
    setStatus(next);
    setJobs((prev) => {
      const merged = new Map(prev);
      for (const job of next.jobs) merged.set(job.spotifyId, job);
      return merged;
    });
    return next;
  }, []);

  useEffect(() => {
    if (!enabled) return;
    // Subscribing to an external system (the core); state is set when it answers.
    refreshStatus().catch(() => {});
  }, [enabled, refreshOn, refreshStatus]);

  useEffect(() => {
    if (!enabled) return;
    refreshRecords(idsKey ? idsKey.split(",") : []).catch(() => {});
  }, [enabled, idsKey, refreshRecords]);

  useEffect(() => {
    if (!enabled) return;
    const offProgress = rpc.onNotification("download.progress", (params) => {
      const job = params as DownloadJob;
      if (job.jobId === INSTALL_JOB) {
        setInstallState({
          state: job.state === "done" || job.state === "failed" ? job.state : "downloading",
          message: job.message ?? "",
        });
        // Tools just changed: re-read what is installed.
        if (job.state === "done" || job.state === "failed") {
          void refreshStatus().catch(() => {});
        }
        return;
      }
      setJobs((prev) => new Map(prev).set(job.spotifyId, job));
      if (job.state === "done" || job.state === "failed") {
        void refreshRecords([job.spotifyId]).catch(() => {});
      }
    });
    const offQueue = rpc.onNotification("download.queue", (params) => {
      setStatus((prev) =>
        prev ? { ...prev, paused: !!params.paused, reason: String(params.reason ?? "") } : prev,
      );
    });
    return () => {
      offProgress();
      offQueue();
    };
  }, [enabled, refreshRecords, refreshStatus]);

  const anyActive = [...jobs.values()].some((job) => ACTIVE.has(job.state));
  useEffect(() => {
    if (isTauri() || !enabled || !anyActive) return;
    const timer = window.setInterval(() => {
      void refreshStatus()
        .then((next) => {
          const finished = next.jobs
            .filter((job) => job.state === "done")
            .map((job) => job.spotifyId);
          return refreshRecords(finished);
        })
        .catch(() => {});
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [enabled, anyActive, refreshStatus, refreshRecords]);

  const enqueue = useCallback(
    async (playlistName: string, tracks: SpotifyTrack[]) => {
      const results = await rpc.call<DownloadJob[]>("downloader.enqueue", {
        playlistName,
        tracks: tracks.map((t) => ({
          spotifyId: t.id,
          url: t.url,
          name: t.name,
          artists: t.artists,
          album: t.album,
          isrc: t.isrc,
        })),
      });
      // The core also notifies, but over HTTP there is no stream: seed from the reply.
      setJobs((prev) => {
        const next = new Map(prev);
        // Enqueue replies are summaries without a message.
        for (const job of results) next.set(job.spotifyId, { ...job, message: job.message ?? "" });
        return next;
      });
    },
    [],
  );

  const cancel = useCallback(async (jobId?: string) => {
    await rpc.call("downloader.cancel", jobId ? { jobId } : {});
  }, []);

  const resume = useCallback(async () => {
    await rpc.call("downloader.resume");
    setStatus((prev) => (prev ? { ...prev, paused: false, reason: "" } : prev));
  }, []);

  const install = useCallback(async () => {
    setInstallState({ state: "downloading", message: "" });
    try {
      await rpc.call("downloader.install");
      // Over HTTP there is no notification stream and install is not in status.jobs:
      // poll until both tools are present.
      if (!isTauri()) {
        const deadline = Date.now() + INSTALL_GIVE_UP_MS;
        for (;;) {
          await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));
          const next = await refreshStatus();
          if (next.spotdl.path && next.ffmpeg) {
            setInstallState({ state: "done", message: "" });
            return;
          }
          if (Date.now() > deadline) {
            setInstallState({
              state: "failed",
              message: "Timed out waiting for spotDL; check the core log.",
            });
            return;
          }
        }
      }
    } catch (error) {
      setInstallState({
        state: "failed",
        message: error instanceof Error ? error.message : String(error),
      });
      throw error;
    }
  }, [refreshStatus]);

  return { jobs, records, status, refreshStatus, installState, enqueue, cancel, resume, install };
}
