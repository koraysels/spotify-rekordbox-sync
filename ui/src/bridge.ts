import { emit, listen } from "@tauri-apps/api/event";

import { rpc, isTauri } from "./rpc";

/**
 * Cross-window RPC.
 *
 * The sidecar is a child process owned by whichever window spawned it — the
 * main window. A second OS window cannot inherit that process, and spawning a
 * second one would mean two processes writing the same rekordbox database. So
 * secondary windows forward their calls to the main window over Tauri events
 * and get the answer back the same way.
 */

interface Request {
  id: number;
  method: string;
  params: Record<string, unknown>;
}

interface Response {
  id: number;
  result?: unknown;
  error?: string;
}

const REQUEST = "rpc:request";
const RESPONSE = "rpc:response";
const PROGRESS = "rpc:progress";

/** Run in the main window: serve calls coming from other windows. */
export async function serveRpcToOtherWindows(): Promise<void> {
  if (!isTauri()) return;

  await listen<Request>(REQUEST, async (event) => {
    const { id, method, params } = event.payload;
    try {
      const result = await rpc.call<unknown>(method, params);
      await emit(RESPONSE, { id, result } satisfies Response);
    } catch (cause) {
      await emit(RESPONSE, {
        id,
        error: cause instanceof Error ? cause.message : String(cause),
      } satisfies Response);
    }
  });

  // Progress notifications originate in the main window; mirror them so the
  // sync window can show what a long operation is doing.
  rpc.onProgress((message) => {
    void emit(PROGRESS, message);
  });
}

let nextId = 1;
const pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
let listening = false;

async function ensureListening(): Promise<void> {
  if (listening) return;
  listening = true;
  await listen<Response>(RESPONSE, (event) => {
    const entry = pending.get(event.payload.id);
    if (!entry) return;
    pending.delete(event.payload.id);
    if (event.payload.error) entry.reject(new Error(event.payload.error));
    else entry.resolve(event.payload.result);
  });
}

/** Run in a secondary window: forward a call to the main window. */
export async function callViaMainWindow<T>(
  method: string,
  params: Record<string, unknown> = {},
): Promise<T> {
  await ensureListening();
  const id = nextId++;
  const promise = new Promise<T>((resolve, reject) => {
    pending.set(id, { resolve: resolve as (v: unknown) => void, reject });
    // Never hang forever if the main window went away.
    window.setTimeout(() => {
      if (pending.delete(id)) {
        reject(new Error("The main rbsync window did not answer. Is it still open?"));
      }
    }, 600_000);
  });
  await emit(REQUEST, { id, method, params } satisfies Request);
  return promise;
}

export function onMainWindowProgress(handler: (message: string) => void): () => void {
  let dispose: (() => void) | null = null;
  void listen<string>(PROGRESS, (event) => handler(event.payload)).then((un) => {
    dispose = un;
  });
  return () => dispose?.();
}
