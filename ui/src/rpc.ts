import { Command, type Child } from "@tauri-apps/plugin-shell";

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

  async stop(): Promise<void> {
    await this.child?.kill();
    this.child = null;
  }
}

export const rpc = new RpcClient();
