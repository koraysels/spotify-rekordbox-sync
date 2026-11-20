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

/** Latest spotDL install progress; `message` carries the failure reason. */
export interface InstallState {
  state: "idle" | "downloading" | "done" | "failed";
  message: string;
}

/**
 * Download state for a set of tracks.
 *
 * Live job progress arrives as `download.progress` notifications; finished
 * downloads are read back from `downloads.get` so the file's existence is
 * checked on disk. In browser dev mode there is no notification stream, so
 * the status is polled while anything is in flight.
 */
export function useDownloads(spotifyIds: string[]) {
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
    // Subscribing to an external system (the core); state is set when it answers.
    refreshStatus().catch(() => {});
  }, [refreshStatus]);

  useEffect(() => {
    refreshRecords(idsKey ? idsKey.split(",") : []).catch(() => {});
  }, [idsKey, refreshRecords]);

  useEffect(() => {
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
  }, [refreshRecords, refreshStatus]);

  const anyActive = [...jobs.values()].some((job) => ACTIVE.has(job.state));
  useEffect(() => {
    if (isTauri() || !anyActive) return;
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
  }, [anyActive, refreshStatus, refreshRecords]);

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
    } catch (error) {
      setInstallState({
        state: "failed",
        message: error instanceof Error ? error.message : String(error),
      });
      throw error;
    }
  }, []);

  return { jobs, records, status, installState, enqueue, cancel, resume, install };
}
