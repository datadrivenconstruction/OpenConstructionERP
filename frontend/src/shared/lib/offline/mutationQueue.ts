// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Offline mutation queue — captures field-report / daily-diary writes made while
 * offline and replays them in order when connectivity returns.
 *
 * Design goals (see internal design note impl/08-field-pwa sections 4.4 and 8):
 *
 *  - FIFO ordering: a punch item created offline must replay before the photo
 *    that references it, so the queue drains strictly in enqueue order.
 *  - Idempotent replay: every queued op carries a client-generated `clientOpId`.
 *    A duplicate enqueue (same `clientOpId`) is collapsed, and the server is
 *    expected to dedup on the same key, so draining the queue more than once
 *    (the classic "reconnect fired twice" case) never creates duplicate rows.
 *  - Per-item success/failure: the drain reports the outcome of every op so the
 *    UI can show "N synced, M conflicts/rejected" rather than a silent drop.
 *  - Retry on transient failure: a network error or 5xx leaves the op in the
 *    queue with an incremented retry count; a 2xx/409 removes it (409 means the
 *    server already has it); a non-409 4xx marks it rejected and removes it so
 *    the client stops retrying a permanently-bad payload.
 *  - Backoff (opt-in): with `backoff` set, a transient failure also stamps
 *    `nextAttemptAt` (exponential, capped, jittered) and the drain skips ops that
 *    are not yet due. Ops sharing a `meta.recordKey` keep their order: while one
 *    is waiting or conflicted, later ones for the same record wait too.
 *  - Version conflict: a 409 for a versioned update arrives as `merge_conflict`.
 *    The op stays queued, flagged with the server's current object, and is not
 *    replayed until the caller resolves it (`resolveMergeConflict`) or discards it.
 *
 * Storage is injected (`QueueStorage`) so the pure queue logic is unit-testable
 * in jsdom without a real IndexedDB. `createIndexedDbQueueStorage()` provides the
 * browser-backed adapter; `createMemoryQueueStorage()` backs the tests.
 */

/* ── Types ─────────────────────────────────────────────────────────────── */

export type HttpMethod = 'POST' | 'PUT' | 'PATCH' | 'DELETE';

/** The outcome the sender reports back for a single replayed op. */
export type ReplayOutcome =
  | { kind: 'applied'; httpStatus: number; resultId?: string | null }
  | { kind: 'conflict'; httpStatus: number; detail?: string }
  | { kind: 'rejected'; httpStatus: number; detail?: string }
  | {
      kind: 'merge_conflict';
      httpStatus: number;
      detail?: string;
      currentVersion?: number;
      current?: unknown;
    }
  | { kind: 'retry'; httpStatus?: number; detail?: string };

/** The server's side of a version conflict, kept on the op until it is merged. */
export interface MergeConflictInfo {
  message?: string;
  currentVersion?: number;
  /** Full server object from the 409 body. */
  current?: unknown;
  detectedAt: number;
}

/** A mutation captured while offline, awaiting replay. */
export interface QueuedOp {
  /** Monotonic enqueue sequence; the FIFO sort key. Assigned by the queue. */
  seq: number;
  /** Client-generated idempotency key. The dedup key on both client and server. */
  clientOpId: string;
  /** HTTP verb of the original write. */
  method: HttpMethod;
  /** API path, e.g. `/v1/field-diary/capture/punch/`. */
  path: string;
  /** JSON-serialisable request body. */
  body?: unknown;
  /** Logical target, e.g. `field_report`, `daily_diary` — for UI grouping. */
  kind: string;
  /** Epoch ms when the op was captured on the device. */
  queuedAt: number;
  /** How many replay attempts have failed transiently so far. */
  retries: number;
  /** Epoch ms before which a backoff-enabled drain will not retry this op. */
  nextAttemptAt?: number;
  /** Set when the server answered a versioned write with a version conflict. */
  conflict?: MergeConflictInfo;
  /** Free-form routing data for the sender (record key, entity, photo id...). */
  meta?: Record<string, unknown>;
}

/** What a drain run reports back to the caller per op. */
export interface DrainResult {
  clientOpId: string;
  kind: string;
  status: 'applied' | 'conflict' | 'rejected' | 'retry' | 'merge_conflict';
  httpStatus?: number;
  detail?: string;
  resultId?: string | null;
}

/** Aggregate counts from a drain run. */
export interface DrainSummary {
  applied: number;
  conflict: number;
  rejected: number;
  retry: number;
  /** Versioned writes parked for a merge (still in the queue). */
  merge_conflict: number;
  results: DrainResult[];
}

/**
 * Sends one op to the server and reports the outcome. Injected so the queue is
 * transport-agnostic and testable. Must not throw for an HTTP error — return a
 * `retry` outcome instead so the queue can keep the op. May throw for a true
 * network failure; the queue treats a thrown error as a transient retry.
 */
export type OpSender = (op: QueuedOp) => Promise<ReplayOutcome>;

/** Pluggable persistence for the queue. */
export interface QueueStorage {
  getAll(): Promise<QueuedOp[]>;
  put(op: QueuedOp): Promise<void>;
  remove(clientOpId: string): Promise<void>;
  clear(): Promise<void>;
}

/* ── Pure helpers ──────────────────────────────────────────────────────── */

function recordKeyOf(op: QueuedOp): string | null {
  const k = op.meta?.recordKey;
  return typeof k === 'string' && k ? k : null;
}

/** Sort ops into FIFO replay order without mutating the input. */
export function sortByFifo(ops: readonly QueuedOp[]): QueuedOp[] {
  return [...ops].sort((a, b) => a.seq - b.seq);
}

/**
 * Generate a client op id. Uses `crypto.randomUUID` when present (every modern
 * browser and Node 19+), with a non-crypto fallback so the helper never throws
 * in a bare test realm.
 */
export function newClientOpId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c && typeof c.randomUUID === 'function') {
    return c.randomUUID();
  }
  return `op-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/* ── In-memory storage (tests + SSR-safe fallback) ─────────────────────── */

/**
 * In-memory queue storage. Backs the unit tests and is the safe fallback when
 * IndexedDB is unavailable (private mode, locked-down WebViews) so the queue
 * still functions for the lifetime of the tab.
 */
export function createMemoryQueueStorage(): QueueStorage {
  const map = new Map<string, QueuedOp>();
  return {
    getAll: () => Promise.resolve([...map.values()]),
    put: (op) => {
      map.set(op.clientOpId, op);
      return Promise.resolve();
    },
    remove: (clientOpId) => {
      map.delete(clientOpId);
      return Promise.resolve();
    },
    clear: () => {
      map.clear();
      return Promise.resolve();
    },
  };
}

/* ── IndexedDB storage ─────────────────────────────────────────────────── */

const DB_NAME = 'oe_field_offline';
const DB_VERSION = 1;
const STORE = 'fieldMutationQueue';

function openDb(dbName: string): Promise<IDBDatabase> {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open(dbName, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        // Keyed by clientOpId so an enqueue with a seen id overwrites rather
        // than duplicates — the storage-level half of the dedup guarantee.
        db.createObjectStore(STORE, { keyPath: 'clientOpId' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/**
 * IndexedDB-backed queue storage used in the browser. Every method degrades to
 * a no-op / empty result on failure so a storage error never crashes a capture;
 * the in-memory fallback should be used when `indexedDB` is absent.
 *
 * A second surface gets a second *database*, never a second object store in
 * this one. `onupgradeneeded` only fires when the version rises, so a browser
 * that has already opened `oe_field_offline` at version 1 would never create a
 * newly-added store: every write would throw `NotFoundError`, and these methods
 * swallow it. The queue would accept entries and lose all of them, which is the
 * exact inverse of what it is for. Passing a distinct `dbName` keeps each
 * surface's upgrade path independent.
 */
export function createIndexedDbQueueStorage(dbName: string = DB_NAME): QueueStorage {
  let dbPromise: Promise<IDBDatabase> | null = null;
  const db = (): Promise<IDBDatabase> => {
    if (!dbPromise) dbPromise = openDb(dbName);
    return dbPromise;
  };

  return {
    async getAll() {
      try {
        const conn = await db();
        return await new Promise<QueuedOp[]>((resolve) => {
          const tx = conn.transaction(STORE, 'readonly');
          const req = tx.objectStore(STORE).getAll();
          req.onsuccess = () => resolve((req.result as QueuedOp[]) ?? []);
          req.onerror = () => resolve([]);
        });
      } catch {
        return [];
      }
    },
    async put(op) {
      try {
        const conn = await db();
        await new Promise<void>((resolve, reject) => {
          const tx = conn.transaction(STORE, 'readwrite');
          tx.objectStore(STORE).put(op);
          tx.oncomplete = () => resolve();
          tx.onerror = () => reject(tx.error);
        });
      } catch {
        /* storage unavailable — caller keeps the in-memory copy */
      }
    },
    async remove(clientOpId) {
      try {
        const conn = await db();
        await new Promise<void>((resolve) => {
          const tx = conn.transaction(STORE, 'readwrite');
          tx.objectStore(STORE).delete(clientOpId);
          tx.oncomplete = () => resolve();
          tx.onerror = () => resolve();
        });
      } catch {
        /* ignore */
      }
    },
    async clear() {
      try {
        const conn = await db();
        await new Promise<void>((resolve) => {
          const tx = conn.transaction(STORE, 'readwrite');
          tx.objectStore(STORE).clear();
          tx.oncomplete = () => resolve();
          tx.onerror = () => resolve();
        });
      } catch {
        /* ignore */
      }
    },
  };
}

/* ── The queue ─────────────────────────────────────────────────────────── */

export interface EnqueueInput {
  clientOpId?: string;
  method: HttpMethod;
  path: string;
  body?: unknown;
  kind: string;
  meta?: Record<string, unknown>;
}

/** Exponential backoff with jitter for transient retries. */
export interface BackoffOptions {
  /** Delay after the first failure. Default 2000 ms. */
  baseMs?: number;
  /** Growth factor per further failure. Default 2. */
  factor?: number;
  /** Upper bound of the delay. Default 300000 ms (5 min). */
  capMs?: number;
}

export const DEFAULT_BACKOFF: Required<BackoffOptions> = { baseMs: 2000, factor: 2, capMs: 300_000 };

/**
 * Delay before retry number `retries` (1 = after the first failure). The
 * exponential value is capped, then jittered into [50%, 100%] of itself so a
 * crowd of devices reconnecting together does not retry in lockstep.
 */
export function computeBackoffDelay(
  retries: number,
  opts: BackoffOptions = {},
  random: () => number = Math.random,
): number {
  const { baseMs, factor, capMs } = { ...DEFAULT_BACKOFF, ...opts };
  const raw = Math.min(capMs, baseMs * Math.pow(factor, Math.max(0, retries - 1)));
  return Math.round(raw * (0.5 + random() * 0.5));
}

export interface MutationQueueOptions {
  /** Enable exponential backoff for transient failures. Off by default. */
  backoff?: boolean | BackoffOptions;
  /** Clock and randomness seams for tests. */
  now?: () => number;
  random?: () => number;
  /** Max ops attempted per drain pass (bounds a huge backlog). Default 50. */
  maxPerDrain?: number;
  /** Max transient retries before an op is given up and removed. Default 8. */
  maxRetries?: number;
}

/**
 * The offline mutation queue. One instance per logical surface (the field shell
 * constructs one). Construct with a `QueueStorage` and an `OpSender`.
 */
export class MutationQueue {
  private readonly storage: QueueStorage;
  private readonly sender: OpSender;
  private readonly maxPerDrain: number;
  private readonly maxRetries: number;
  private readonly backoff: Required<BackoffOptions> | null;
  private readonly now: () => number;
  private readonly random: () => number;
  private seqCounter = 0;
  private draining = false;
  private readonly changeListeners = new Set<() => void>();

  constructor(storage: QueueStorage, sender: OpSender, options: MutationQueueOptions = {}) {
    this.storage = storage;
    this.sender = sender;
    this.maxPerDrain = options.maxPerDrain ?? 50;
    this.maxRetries = options.maxRetries ?? 8;
    this.backoff = options.backoff
      ? { ...DEFAULT_BACKOFF, ...(options.backoff === true ? {} : options.backoff) }
      : null;
    this.now = options.now ?? Date.now;
    this.random = options.random ?? Math.random;
  }

  /** Subscribe to queue-size changes (enqueue / drain). Returns unsubscribe. */
  onChange(listener: () => void): () => void {
    this.changeListeners.add(listener);
    return () => {
      this.changeListeners.delete(listener);
    };
  }

  private notify(): void {
    for (const l of [...this.changeListeners]) l();
  }

  /** Count of ops still awaiting replay. */
  async pendingCount(): Promise<number> {
    const ops = await this.storage.getAll();
    return ops.length;
  }

  /** All pending ops in FIFO order (for a "pending sync" review list). */
  async pending(): Promise<QueuedOp[]> {
    return sortByFifo(await this.storage.getAll());
  }

  /**
   * Enqueue a mutation for later replay. Idempotent on `clientOpId`: enqueuing
   * the same id twice keeps the first op's sequence (so ordering is stable) and
   * does not create a second entry.
   */
  async enqueue(input: EnqueueInput): Promise<QueuedOp> {
    const clientOpId = input.clientOpId ?? newClientOpId();
    const existing = await this.findByClientOpId(clientOpId);
    if (existing) {
      // Dedup: a re-enqueue of the same op is a no-op, returning the original.
      return existing;
    }
    const op: QueuedOp = {
      seq: this.nextSeq(),
      clientOpId,
      method: input.method,
      path: input.path,
      body: input.body,
      kind: input.kind,
      queuedAt: Date.now(),
      retries: 0,
      ...(input.meta ? { meta: input.meta } : {}),
    };
    await this.storage.put(op);
    this.notify();
    return op;
  }

  /**
   * Replay queued ops in FIFO order. Stops at `maxPerDrain`. A drain already in
   * progress short-circuits so two reconnect events cannot interleave (the
   * second returns an empty summary). Returns a per-op summary.
   */
  async drain(opts: { ignoreBackoff?: boolean } = {}): Promise<DrainSummary> {
    const summary: DrainSummary = {
      applied: 0,
      conflict: 0,
      rejected: 0,
      retry: 0,
      merge_conflict: 0,
      results: [],
    };
    if (this.draining) return summary;
    this.draining = true;
    try {
      const all = sortByFifo(await this.storage.getAll());
      const now = this.now();
      const blocked = new Set<string>();
      const due: QueuedOp[] = [];
      for (const op of all) {
        const key = recordKeyOf(op);
        if (key && blocked.has(key)) continue;
        if (op.conflict) {
          if (key) blocked.add(key);
          continue;
        }
        if (!opts.ignoreBackoff && op.nextAttemptAt !== undefined && op.nextAttemptAt > now) {
          if (key) blocked.add(key);
          continue;
        }
        due.push(op);
      }
      for (const op of due.slice(0, this.maxPerDrain)) {
        const key = recordKeyOf(op);
        if (key && blocked.has(key)) continue;
        const result = await this.replayOne(op);
        summary.results.push(result);
        summary[result.status] += 1;
        // A failed or parked op holds back the later ops on the same record.
        if (key && (result.status === 'retry' || result.status === 'merge_conflict')) {
          blocked.add(key);
        }
      }
    } finally {
      this.draining = false;
    }
    if (summary.applied + summary.conflict + summary.rejected + summary.merge_conflict > 0) {
      this.notify();
    }
    return summary;
  }

  /** Earliest `nextAttemptAt` among waiting ops, or null when none is waiting. */
  async nextDueAt(): Promise<number | null> {
    const times = (await this.storage.getAll())
      .filter((o) => !o.conflict && o.nextAttemptAt !== undefined)
      .map((o) => o.nextAttemptAt as number);
    return times.length > 0 ? Math.min(...times) : null;
  }

  /** Ops parked on a version conflict, FIFO. */
  async conflicts(): Promise<QueuedOp[]> {
    return sortByFifo((await this.storage.getAll()).filter((o) => o.conflict));
  }

  /** Refresh the server copy on a parked op (the merge itself hit a newer version). */
  async markConflict(clientOpId: string, info: Omit<MergeConflictInfo, 'detectedAt'>): Promise<void> {
    const existing = await this.findByClientOpId(clientOpId);
    if (!existing) return;
    await this.storage.put({ ...existing, conflict: { ...info, detectedAt: this.now() } });
    this.notify();
  }

  /**
   * The merge was posted (or the user chose to keep the server copy): drop the
   * parked op so the record's later ops can replay.
   */
  async resolveMergeConflict(clientOpId: string): Promise<void> {
    await this.storage.remove(clientOpId);
    this.notify();
  }

  private async replayOne(op: QueuedOp): Promise<DrainResult> {
    let outcome: ReplayOutcome;
    try {
      outcome = await this.sender(op);
    } catch {
      // A thrown error is a true transport failure: keep the op, count a retry.
      outcome = { kind: 'retry' };
    }

    if (outcome.kind === 'applied') {
      await this.storage.remove(op.clientOpId);
      return {
        clientOpId: op.clientOpId,
        kind: op.kind,
        status: 'applied',
        httpStatus: outcome.httpStatus,
        resultId: outcome.resultId ?? null,
      };
    }

    if (outcome.kind === 'conflict') {
      // The server already has an equivalent row (idempotency hit). Safe to drop
      // from the queue; surface it so the UI can offer "review".
      await this.storage.remove(op.clientOpId);
      return {
        clientOpId: op.clientOpId,
        kind: op.kind,
        status: 'conflict',
        httpStatus: outcome.httpStatus,
        detail: outcome.detail,
      };
    }

    if (outcome.kind === 'merge_conflict') {
      // Versioned update lost the race. Keep the op and the server's copy so
      // the merge can be done later (possibly across a reload); never drop.
      await this.storage.put({
        ...op,
        conflict: {
          message: outcome.detail,
          currentVersion: outcome.currentVersion,
          current: outcome.current,
          detectedAt: this.now(),
        },
      });
      return {
        clientOpId: op.clientOpId,
        kind: op.kind,
        status: 'merge_conflict',
        httpStatus: outcome.httpStatus,
        detail: outcome.detail,
      };
    }

    if (outcome.kind === 'rejected') {
      // Permanently bad payload (validation): stop retrying, drop it.
      await this.storage.remove(op.clientOpId);
      return {
        clientOpId: op.clientOpId,
        kind: op.kind,
        status: 'rejected',
        httpStatus: outcome.httpStatus,
        detail: outcome.detail,
      };
    }

    // retry: transient. Bump the counter and keep it, unless we've given up.
    const retries = op.retries + 1;
    if (retries >= this.maxRetries) {
      await this.storage.remove(op.clientOpId);
      return {
        clientOpId: op.clientOpId,
        kind: op.kind,
        status: 'rejected',
        httpStatus: outcome.httpStatus,
        detail: outcome.detail ?? 'gave up after max retries',
      };
    }
    await this.storage.put({
      ...op,
      retries,
      ...(this.backoff
        ? { nextAttemptAt: this.now() + computeBackoffDelay(retries, this.backoff, this.random) }
        : {}),
    });
    return {
      clientOpId: op.clientOpId,
      kind: op.kind,
      status: 'retry',
      httpStatus: outcome.httpStatus,
      detail: outcome.detail,
    };
  }

  /** Remove a single op (e.g. user discards a conflicted item). */
  async discard(clientOpId: string): Promise<void> {
    await this.storage.remove(clientOpId);
    this.notify();
  }

  /** Drop everything (e.g. field session sign-out clears the queue). */
  async clear(): Promise<void> {
    await this.storage.clear();
    this.notify();
  }

  private async findByClientOpId(clientOpId: string): Promise<QueuedOp | undefined> {
    const ops = await this.storage.getAll();
    return ops.find((o) => o.clientOpId === clientOpId);
  }

  private nextSeq(): number {
    // Monotonic across the instance; ms-time base keeps ordering stable even if
    // a fresh instance is constructed after a reload, since enqueue order within
    // a session is what matters and storage replays in seq order.
    const base = Date.now();
    this.seqCounter = Math.max(this.seqCounter + 1, base);
    return this.seqCounter;
  }
}
