// OpenConstructionERP — DataDrivenConstruction (DDC)​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// CWICR AI Estimation Engine — quick-estimate history hook
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// DDC-CWICR-OE-2026
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';
import type { EstimateJobResponse } from './api';

// ── Constants ────────────────────────────────────────────────────────────────

/** LRU cap on stored history entries per user. */
export const HISTORY_MAX = 20;

/** Schema version — bumping invalidates older payloads. */
export const HISTORY_SCHEMA_VERSION = 1;

/** Prefix for the per-user localStorage key. */
export const HISTORY_KEY_PREFIX = 'oe_ai_estimate_history_';

/** Run outcomes the hook tracks. Mirrors the spec. */
export type HistoryStatus = 'ok' | 'cancelled' | 'error';

// ── Types ────────────────────────────────────────────────────────────────────

/** A single entry persisted to localStorage. */
export interface HistoryEntry {
  /** Stable id (uuid-ish, but any unique non-empty string works). */
  id: string;
  /** ISO-8601 timestamp. */
  createdAt: string;
  /** The prompt the user submitted (or "(empty)" if they ran via paste/example). */
  prompt: string;
  /**
   * The estimate result. `null` for cancelled/error runs that never produced
   * a job response. Stored as a plain object — no Date/Map/Set instances.
   */
  result: EstimateJobResponse | null;
  /** Model id that produced the result (e.g. "claude-sonnet"). May be empty for errors. */
  model: string;
  /**
   * Estimated cost in USD. We don't currently log cost server-side, so the
   * UI passes 0 by default — keeping the field reserved means future cost
   * surfacing won't need a migration.
   */
  costUsd: number;
  /** Duration in ms (server-reported for ok runs, wall-clock for cancel/error). */
  durationMs: number;
  /** Outcome of the run. */
  status: HistoryStatus;
  /** Optional error message for status==='error'. */
  errorMessage?: string;
}

/** Shape persisted to localStorage. The `v` field enables future migration. */
interface HistoryEnvelope {
  v: number;
  entries: HistoryEntry[];
}

// ── Storage helpers ──────────────────────────────────────────────────────────

/**
 * Compute the per-user storage key.
 *
 * Falls back to a literal "anonymous" bucket when the user isn't identified
 * (e.g. during the brief window between login and the auth store hydrating).
 * Keeping a stable key means the user sees their pre-login work after the
 * store settles instead of an empty list.
 */
export function historyStorageKey(userId: string | null | undefined): string {
  const id = (userId || '').trim() || 'anonymous';
  return `${HISTORY_KEY_PREFIX}${id}`;
}

/**
 * Read history from localStorage. Returns `[]` on:
 * - missing key
 * - JSON parse errors
 * - schema-version mismatch
 * - shape mismatch (e.g. someone hand-edited the value)
 *
 * Every storage access is wrapped in try/catch — Safari's "private mode"
 * historically throws on `setItem`, and corporate group-policy can disable
 * the storage API entirely.
 */
export function readHistory(key: string): HistoryEntry[] {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object') return [];
    const env = parsed as Partial<HistoryEnvelope>;
    if (env.v !== HISTORY_SCHEMA_VERSION) return [];
    if (!Array.isArray(env.entries)) return [];
    // Filter out malformed entries defensively.
    return env.entries.filter(
      (e): e is HistoryEntry =>
        !!e &&
        typeof e === 'object' &&
        typeof (e as HistoryEntry).id === 'string' &&
        typeof (e as HistoryEntry).createdAt === 'string' &&
        typeof (e as HistoryEntry).prompt === 'string' &&
        typeof (e as HistoryEntry).status === 'string',
    );
  } catch {
    return [];
  }
}

/** Persist history to localStorage. Silently no-ops on storage errors. */
export function writeHistory(key: string, entries: HistoryEntry[]): void {
  try {
    const envelope: HistoryEnvelope = { v: HISTORY_SCHEMA_VERSION, entries };
    window.localStorage.setItem(key, JSON.stringify(envelope));
  } catch {
    // Storage full / disabled / private mode — drop the write silently.
  }
}

/**
 * Apply LRU eviction. New entries are appended at the FRONT so the UI can
 * render newest-first without sorting on every read; oldest entries fall
 * off the back when the list exceeds `HISTORY_MAX`.
 */
export function lruInsert(
  existing: HistoryEntry[],
  next: HistoryEntry,
  cap: number = HISTORY_MAX,
): HistoryEntry[] {
  // Strip any prior entry with the same id (re-appended runs jump to front).
  const deduped = existing.filter((e) => e.id !== next.id);
  const merged = [next, ...deduped];
  if (merged.length <= cap) return merged;
  return merged.slice(0, cap);
}

// ── Hook ─────────────────────────────────────────────────────────────────────

/** Public return shape of the hook. */
export interface UseQuickEstimateHistory {
  /** Newest-first list of entries. */
  history: HistoryEntry[];
  /** Append a new entry with LRU eviction. */
  append: (entry: HistoryEntry) => void;
  /** Wipe all entries for the active user. */
  clear: () => void;
  /** Look up an entry by id (does not mutate state). */
  restore: (id: string) => HistoryEntry | undefined;
}

/**
 * React hook that exposes the per-user Quick-Estimate history.
 *
 * Storage is keyed by the user's email (the auth store doesn't expose a
 * dedicated user-id) and isolated to that user. The hook reloads from
 * localStorage whenever the active user changes so account switches in
 * the same browser session don't leak entries.
 */
export function useQuickEstimateHistory(): UseQuickEstimateHistory {
  const userEmail = useAuthStore((s) => s.userEmail);
  const key = useMemo(() => historyStorageKey(userEmail), [userEmail]);

  const [history, setHistory] = useState<HistoryEntry[]>(() => readHistory(key));

  // Reload when the user (and therefore the key) changes.
  useEffect(() => {
    setHistory(readHistory(key));
  }, [key]);

  const append = useCallback(
    (entry: HistoryEntry) => {
      setHistory((prev) => {
        const next = lruInsert(prev, entry);
        writeHistory(key, next);
        return next;
      });
    },
    [key],
  );

  const clear = useCallback(() => {
    writeHistory(key, []);
    setHistory([]);
  }, [key]);

  const restore = useCallback(
    (id: string) => history.find((e) => e.id === id),
    [history],
  );

  return { history, append, clear, restore };
}
