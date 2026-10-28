// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Per-project clash-filter persistence (Wave A5).
 *
 * Currently the severity / status / discipline / sortBy filters in
 * `ClashDetectionPage` reset on every page reload — the coordinator has
 * to re-build them every time they hop between two projects.
 *
 * This module persists them per-project_id in `localStorage` under the
 * key family `clash_filters_{project_id}`, hydrates on mount, throttles
 * writes (200 ms debounce), and evicts the oldest project's entry once
 * the project count exceeds `MAX_PROJECTS` (LRU).
 *
 * Schema is versioned (`v: 1`) so a future format change can ship a
 * one-shot migration instead of nuking everyone's saved filters.
 *
 * Defensive about every storage interaction: `localStorage` is unavailable
 * in SSR, in privacy mode, or when the user's quota is full — every
 * read/write is wrapped in try/catch and degrades to "no persistence"
 * instead of crashing the page.
 */

/** localStorage key for a single project's saved filter state. */
export const filterKey = (projectId: string): string =>
  `clash_filters_${projectId}`;

/** localStorage key for the LRU index (project_id ordered newest-first). */
export const lruKey = 'clash_filters_lru_v1';

/** Schema version stored alongside the payload. Bump on shape changes. */
export const FILTER_SCHEMA_VERSION = 1 as const;

/** Maximum projects to retain — anything older is evicted (LRU). */
export const MAX_PROJECTS = 5;

/** Debounce window for persistence writes (ms). */
export const PERSIST_DEBOUNCE_MS = 200;

/**
 * The serialisable shape of one project's saved filters.
 *
 * Only stable, lightweight identifiers — never opaque object refs — go
 * in here. Adding a new field is safe (defaulted on hydrate); removing
 * one requires a schema-version bump.
 */
export interface ClashFilterState {
  /** Selected severities (subset of the `ClashSeverity` enum). */
  severity: string[];
  /** Selected result statuses. */
  status: string[];
  /** Selected discipline pairs (ordered "A|B" keys). */
  discipline: string[];
  /** Active sort column id. */
  sortBy: string;
}

/** The envelope written to localStorage. `v` is the schema version. */
export interface PersistedFilterEnvelope {
  v: typeof FILTER_SCHEMA_VERSION;
  filters: ClashFilterState;
  /** Last-touched timestamp (ms since epoch) — drives the LRU eviction. */
  updatedAt: number;
}

/** Empty / default filter state — used by the hydrate-mismatch fallback. */
export const EMPTY_FILTERS: ClashFilterState = Object.freeze({
  severity: [],
  status: [],
  discipline: [],
  sortBy: 'idx',
}) as ClashFilterState;

/** Best-effort `localStorage` accessor. Returns null when unavailable. */
function getStorage(): Storage | null {
  try {
    if (typeof window === 'undefined' || !window.localStorage) {
      return null;
    }
    return window.localStorage;
  } catch {
    return null;
  }
}

/**
 * Validate + coerce a raw parsed envelope into a real `ClashFilterState`.
 *
 * Returns `null` when the envelope is missing, malformed, or carries a
 * schema version we don't recognise — the caller falls back to the
 * empty default. Forward-compatible: a future `v: 2` payload is read
 * as "unknown" and ignored, never crash-decoded.
 */
export function coerceFilters(raw: unknown): ClashFilterState | null {
  if (!raw || typeof raw !== 'object') return null;
  const env = raw as Partial<PersistedFilterEnvelope>;
  if (env.v !== FILTER_SCHEMA_VERSION) return null;
  const f = env.filters;
  if (!f || typeof f !== 'object') return null;
  // Coerce arrays — drop anything non-string so a tampered payload can
  // never inject a non-string into a `Set<string>` downstream.
  const toStrArr = (xs: unknown): string[] =>
    Array.isArray(xs) ? xs.filter((x) => typeof x === 'string') : [];
  return {
    severity: toStrArr(f.severity),
    status: toStrArr(f.status),
    discipline: toStrArr(f.discipline),
    sortBy: typeof f.sortBy === 'string' && f.sortBy ? f.sortBy : 'idx',
  };
}

/**
 * Load the saved filter state for one project. Empty defaults if absent.
 *
 * Touches the LRU index as a side-effect so subsequent loads see this
 * project as the most-recently-used (it's why we expose `touchLRU`
 * separately — a hydrate IS a use).
 */
export function loadFilters(projectId: string): ClashFilterState {
  const ls = getStorage();
  if (!ls || !projectId) return { ...EMPTY_FILTERS };
  try {
    const raw = ls.getItem(filterKey(projectId));
    if (!raw) return { ...EMPTY_FILTERS };
    const parsed: unknown = JSON.parse(raw);
    const ok = coerceFilters(parsed);
    if (ok === null) {
      // Schema mismatch or corrupted — drop the stale entry so it
      // doesn't keep getting re-tried + return the empty default.
      ls.removeItem(filterKey(projectId));
      return { ...EMPTY_FILTERS };
    }
    touchLRU(projectId);
    return ok;
  } catch {
    return { ...EMPTY_FILTERS };
  }
}

/**
 * Persist the given filter state for one project + update the LRU.
 *
 * Evicts the oldest project beyond `MAX_PROJECTS` so the storage
 * footprint stays bounded even after years of project-hopping. Best-
 * effort: a `localStorage` write failure (quota, privacy mode) is
 * silently swallowed — saving filters is a convenience, never critical.
 */
export function saveFilters(
  projectId: string,
  filters: ClashFilterState,
): void {
  const ls = getStorage();
  if (!ls || !projectId) return;
  const envelope: PersistedFilterEnvelope = {
    v: FILTER_SCHEMA_VERSION,
    filters,
    updatedAt: Date.now(),
  };
  try {
    ls.setItem(filterKey(projectId), JSON.stringify(envelope));
    touchLRU(projectId);
    evictBeyondLimit();
  } catch {
    /* quota exceeded / storage unavailable — degrade silently */
  }
}

/**
 * Mark `projectId` as most-recently-used in the LRU index.
 *
 * The LRU index is a single ordered JSON array of project ids stored in
 * `localStorage`. Adding / re-touching a project moves it to the head;
 * `evictBeyondLimit` trims the tail.
 */
export function touchLRU(projectId: string): void {
  const ls = getStorage();
  if (!ls || !projectId) return;
  try {
    const current = readLRU(ls);
    // Strip then prepend → the project ends up at index 0 (newest).
    const next = [projectId, ...current.filter((id) => id !== projectId)];
    ls.setItem(lruKey, JSON.stringify(next));
  } catch {
    /* read-only storage / quota — ignore */
  }
}

/**
 * Drop the oldest LRU entries (+ their filter blobs) beyond MAX_PROJECTS.
 *
 * Called after every `saveFilters` so storage stays bounded — never
 * called from `loadFilters` (a load shouldn't have side-effects beyond
 * the LRU touch).
 */
export function evictBeyondLimit(): void {
  const ls = getStorage();
  if (!ls) return;
  try {
    const current = readLRU(ls);
    if (current.length <= MAX_PROJECTS) return;
    const keep = current.slice(0, MAX_PROJECTS);
    const drop = current.slice(MAX_PROJECTS);
    for (const id of drop) {
      ls.removeItem(filterKey(id));
    }
    ls.setItem(lruKey, JSON.stringify(keep));
  } catch {
    /* ignore */
  }
}

/** Read the raw LRU array. Empty list when missing / malformed. */
function readLRU(ls: Storage): string[] {
  try {
    const raw = ls.getItem(lruKey);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((x): x is string => typeof x === 'string')
      : [];
  } catch {
    return [];
  }
}

/**
 * Create a debounced wrapper around `saveFilters`.
 *
 * The component creates one of these per project_id and calls it on
 * every filter change; rapid typing/clicking coalesces into a single
 * write after `PERSIST_DEBOUNCE_MS` of quiet time. Returns a `cancel`
 * fn so the caller can flush pending writes on unmount.
 */
export function createDebouncedPersist(): {
  schedule: (projectId: string, filters: ClashFilterState) => void;
  cancel: () => void;
  /** Force-flush whatever is pending right now (e.g. on unmount). */
  flush: () => void;
} {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pending: { projectId: string; filters: ClashFilterState } | null = null;

  const flush = () => {
    if (pending) {
      saveFilters(pending.projectId, pending.filters);
      pending = null;
    }
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  };

  return {
    schedule(projectId, filters) {
      pending = { projectId, filters };
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        if (pending) {
          saveFilters(pending.projectId, pending.filters);
          pending = null;
        }
        timer = null;
      }, PERSIST_DEBOUNCE_MS);
    },
    cancel() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      pending = null;
    },
    flush,
  };
}

/** Read the current LRU index (test helper). Read-only — never mutates. */
export function readLRUForTest(): string[] {
  const ls = getStorage();
  if (!ls) return [];
  return readLRU(ls);
}
