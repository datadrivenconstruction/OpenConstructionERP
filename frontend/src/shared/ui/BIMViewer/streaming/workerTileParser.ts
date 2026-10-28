// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * Main-thread orchestrator for the off-thread GLB tile parser.
 *
 * Owns a single module Worker and turns each tile buffer into a reconstructed
 * THREE.Object3D. The worker parses the GLB and replies with three's own
 * Object3D.toJSON(); we rebuild it here with THREE.ObjectLoader, so hierarchy,
 * node NAMES and materials are round-tripped by three itself - never
 * hand-rebuilt - which keeps the viewer's node-name -> element-id match intact.
 *
 * The public contract is a ROBUST FALLBACK: parse() never rejects and resolves
 * null on ANY failure - worker unavailable, a worker parse error, or a timeout
 * - so the caller can fall back to the existing main-thread parse and never
 * regress. The buffer is CLONED to the worker (not transferred), so the caller
 * keeps its own copy to feed that fallback; tiles are small by construction, so
 * the clone cost is bounded.
 *
 * Live-verify owed: the speed win of moving GLTFLoader.parse off-thread (net of
 * the ObjectLoader rebuild + structured-clone) needs a perf trace on a real
 * large tiled model. Correctness is covered by tests; the magnitude is not yet.
 */

import * as THREE from 'three';

/** Worker request: parse this GLB buffer, tagged with a correlation id. */
export interface ParseRequest {
  id: number;
  buffer: ArrayBuffer;
}

/**
 * Worker reply. On success `json` is Object3D.toJSON() output for ObjectLoader
 * and `names` is the node-name set the worker's parse produced, so the main
 * thread can verify the round-trip preserved every match key.
 */
export type ParseResponse =
  | { id: number; ok: true; json: unknown; names: string[] }
  | { id: number; ok: false };

interface PendingParse {
  resolve: (object: THREE.Object3D | null) => void;
  timer: ReturnType<typeof setTimeout>;
}

export interface WorkerTileParserOptions {
  /** Per-tile budget before giving up and letting the caller fall back (ms). */
  timeoutMs?: number;
  /**
   * Worker factory seam. Defaults to the real module worker. Tests inject a
   * fake so the protocol + fallback run under jsdom (no Worker, no WebGL).
   */
  workerFactory?: () => Worker;
}

const DEFAULT_TIMEOUT_MS = 8000;

function defaultWorkerFactory(): Worker {
  return new Worker(new URL('./tileParse.worker.ts', import.meta.url), { type: 'module' });
}

/** Sorted list of every non-empty node name in an object tree. */
function collectNodeNames(root: THREE.Object3D): string[] {
  const names: string[] = [];
  root.traverse((object) => {
    if (object.name) names.push(object.name);
  });
  names.sort();
  return names;
}

/**
 * True when `object` carries exactly the node-name multiset `expected` (the
 * names the worker's parse produced). Empty names are ignored - they never
 * key a match. Order-independent.
 */
function nodeNamesPreserved(object: THREE.Object3D, expected: readonly string[]): boolean {
  const got = collectNodeNames(object);
  if (got.length !== expected.length) return false;
  const want = [...expected].sort();
  for (let i = 0; i < got.length; i += 1) {
    if (got[i] !== want[i]) return false;
  }
  return true;
}

export class WorkerTileParser {
  private worker: Worker | null = null;
  private readonly objectLoader = new THREE.ObjectLoader();
  private readonly pending = new Map<number, PendingParse>();
  private nextId = 1;
  private broken = false;
  private readonly timeoutMs: number;
  private readonly makeWorker: () => Worker;

  constructor(options: WorkerTileParserOptions = {}) {
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.makeWorker = options.workerFactory ?? defaultWorkerFactory;
  }

  /** True when a dedicated Worker can be constructed here (false in SSR/jsdom). */
  static isSupported(): boolean {
    return typeof Worker !== 'undefined';
  }

  private ensureWorker(): Worker | null {
    if (this.broken) return null;
    if (this.worker) return this.worker;
    try {
      const worker = this.makeWorker();
      worker.onmessage = (event: MessageEvent<ParseResponse>) => this.onMessage(event.data);
      // A worker that crashes (bad bundle, OOM) must not wedge the pipeline -
      // tear it down and let every parse fall back to the main thread.
      worker.onerror = () => this.breakDown();
      this.worker = worker;
      return worker;
    } catch {
      this.broken = true;
      return null;
    }
  }

  private onMessage(message: ParseResponse): void {
    const pending = this.pending.get(message.id);
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pending.delete(message.id);
    if (!message.ok) {
      pending.resolve(null);
      return;
    }
    try {
      const object = this.objectLoader.parse(message.json);
      // Fidelity self-check: the reconstruction must carry the exact node-name
      // set the worker's parse produced. Those names are the keys the viewer's
      // mesh -> element match walks, and a main-thread parse of the same buffer
      // yields the same set, so an identical set means the match ratio cannot
      // degrade. If the round-trip dropped or altered any name, discard the
      // worker scene and resolve null so the caller falls back to a
      // main-thread parse - the silent-break risk becomes an automatic
      // safe fallback.
      if (!nodeNamesPreserved(object, message.names)) {
        pending.resolve(null);
        return;
      }
      pending.resolve(object);
    } catch {
      // A malformed toJSON payload is not fatal - fall back to main thread.
      pending.resolve(null);
    }
  }

  /** A crashed worker fails every outstanding parse and is not reused. */
  private breakDown(): void {
    this.broken = true;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.resolve(null);
    }
    this.pending.clear();
    this.terminate();
  }

  private terminate(): void {
    try {
      this.worker?.terminate();
    } catch {
      /* already gone */
    }
    this.worker = null;
  }

  /**
   * Parse a GLB tile off the main thread. Resolves the reconstructed scene, or
   * null on ANY failure (worker unavailable, parse error, timeout) so the
   * caller can fall back to a main-thread parse.
   */
  parse(buffer: ArrayBuffer): Promise<THREE.Object3D | null> {
    const worker = this.ensureWorker();
    if (!worker) return Promise.resolve(null);
    const id = this.nextId++;
    return new Promise<THREE.Object3D | null>((resolve) => {
      const timer = setTimeout(() => {
        // Give up on a stuck tile so a wedged worker can't stall the stream.
        if (this.pending.delete(id)) resolve(null);
      }, this.timeoutMs);
      this.pending.set(id, { resolve, timer });
      try {
        worker.postMessage({ id, buffer } satisfies ParseRequest);
      } catch {
        clearTimeout(timer);
        this.pending.delete(id);
        resolve(null);
      }
    });
  }

  /** Drop the worker and fail anything still outstanding. */
  dispose(): void {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.resolve(null);
    }
    this.pending.clear();
    this.broken = true;
    this.terminate();
  }
}
