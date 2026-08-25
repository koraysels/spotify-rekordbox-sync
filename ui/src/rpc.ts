import { Command, type Child } from "@tauri-apps/plugin-shell";

/**
 * True when running inside the packaged desktop app.
 *
 * In a plain browser (``npm run dev``) there is no sidecar to spawn, so the
 * client falls back to the core's localhost HTTP bridge — same methods, same
 * payloads, started with ``rbsync serve``.
 */
export const isTauri = (): boolean =>
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

const BRIDGE_URL =
  (import.meta.env?.VITE_RBSYNC_BRIDGE as string | undefined) ??
  "http://127.0.0.1:8765/rpc";

/**
 * Typed client for the Python core.
 *
 * The core runs as a sidecar process and speaks line-delimited JSON-RPC on
 * stdio. Requests are correlated by id, and server-initiated `progress`
 * notifications (which carry no id) are routed to subscribers so long
 * operations can report what they are doing instead of appearing frozen.
 */

interface Pending {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
}

export type ProgressHandler = (message: string) => void;

export class RpcClient {
  private child: Child | null = null;
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private progressHandlers = new Set<ProgressHandler>();
  private buffer = "";

  async start(): Promise<void> {
    if (!isTauri()) return;
    if (this.child) return;

    const command = Command.sidecar("binaries/rbsync-core");
    command.stdout.on("data", (line: string) => this.onStdout(line));
    command.stderr.on("data", (line: string) => console.debug("[core]", line));
    command.on("close", () => {
      this.child = null;
      const error = new Error("The sync engine stopped unexpectedly.");
      this.pending.forEach((p) => p.reject(error));
      this.pending.clear();
    });

    this.child = await command.spawn();
  }

  onProgress(handler: ProgressHandler): () => void {
    this.progressHandlers.add(handler);
    return () => this.progressHandlers.delete(handler);
  }

  private onStdout(chunk: string): void {
    // stdout arrives in arbitrary chunks, so reassemble complete lines.
    this.buffer += chunk;
    let newline = this.buffer.indexOf("\n");
    while (newline >= 0) {
      const line = this.buffer.slice(0, newline).trim();
      this.buffer = this.buffer.slice(newline + 1);
      if (line) this.dispatch(line);
      newline = this.buffer.indexOf("\n");
    }
  }

  private dispatch(line: string): void {
    let message: any;
    try {
      message = JSON.parse(line);
    } catch {
      console.debug("[core] non-JSON output:", line);
      return;
    }

    if (message.id === undefined || message.id === null) {
      if (message.method === "progress") {
        const text = String(message.params?.message ?? "");
        this.progressHandlers.forEach((handler) => handler(text));
      }
      return;
    }

    const pending = this.pending.get(message.id);
    if (!pending) return;
    this.pending.delete(message.id);

    if (message.error) {
      pending.reject(new Error(message.error.message ?? "Unknown error"));
    } else {
      pending.resolve(message.result);
    }
  }

  async call<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    if (!isTauri()) return this.callOverHttp<T>(method, params);

    await this.start();
    if (!this.child) throw new Error("The sync engine is not running.");

    const id = this.nextId++;
    const payload = JSON.stringify({ jsonrpc: "2.0", id, method, params });

    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, {
        resolve: resolve as (value: unknown) => void,
        reject,
      });
      this.child!.write(payload + "\n").catch((error) => {
        this.pending.delete(id);
        reject(error instanceof Error ? error : new Error(String(error)));
      });
    });
  }

  /**
   * Browser-development transport.
   *
   * Progress notifications are not delivered here: HTTP gives one response per
   * request, where stdio gives a stream. Long operations therefore look silent
   * in the browser but still report progress in the packaged app.
   */
  private async callOverHttp<T>(
    method: string,
    params: Record<string, unknown>,
  ): Promise<T> {
    const id = this.nextId++;
    let response: Response;
    try {
      response = await fetch(BRIDGE_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id, method, params }),
      });
    } catch {
      throw new Error(
        `Cannot reach the sync engine at ${BRIDGE_URL}. Start it with: rbsync serve`,
      );
    }
    if (!response.ok) {
      throw new Error(`Sync engine returned HTTP ${response.status}`);
    }
    const message = await response.json();
    if (message.error) throw new Error(message.error.message ?? "Unknown error");
    return message.result as T;
  }

  async stop(): Promise<void> {
    await this.child?.kill();
    this.child = null;
  }
}

export const rpc = new RpcClient();
