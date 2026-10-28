// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Local persistence for Find Records history. Recent searches are the last few
// committed queries, auto-recorded as the user works, and they stay in
// localStorage: they are per-device scratch, nobody needs them on another
// machine, and writing every committed query to the server would be a request
// per keystroke-ending Enter for no benefit.
//
// Saved searches are the deliberate ones the user pinned to re-run later, and
// those live on the server (see ./api) so a pin survives a reload, a cleared
// browser and a different machine. This file no longer stores them.
//
// Every function here swallows storage errors (private mode / quota) so a
// failure never breaks search.

import type { RetrievalQuery } from './types';

// The server row shape, re-exported so importers keep one name for "a pin".
export type { SavedSearch } from './types';

const RECENT_KEY = 'oce.retrieval.recent';
const RECENT_LIMIT = 8;

/** True when a query carries at least one non-empty facet worth remembering. */
export function isMeaningfulQuery(q: RetrievalQuery): boolean {
  return Object.values(q).some((v) => typeof v === 'string' && v.trim() !== '');
}

/** A stable signature so the same facets are de-duplicated in history. */
export function querySignature(q: RetrievalQuery): string {
  return JSON.stringify({
    text: q.text?.trim() ?? '',
    party: q.party?.trim() ?? '',
    record_type: q.record_type?.trim() ?? '',
    date_from: q.date_from?.trim() ?? '',
    date_to: q.date_to?.trim() ?? '',
    entity: q.entity?.trim() ?? '',
  });
}

function readList<T>(key: string): T[] {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

function writeList<T>(key: string, list: T[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(list));
  } catch {
    /* private mode / quota - non-fatal, history just does not persist */
  }
}

/* ── Recent searches ──────────────────────────────────────────────────── */

export function readRecent(): RetrievalQuery[] {
  return readList<RetrievalQuery>(RECENT_KEY);
}

/** Record a committed query at the front of history (most-recent-first),
 *  dropping an earlier copy of the same facets. Empty queries are ignored. */
export function pushRecent(q: RetrievalQuery): RetrievalQuery[] {
  if (!isMeaningfulQuery(q)) return readRecent();
  const sig = querySignature(q);
  const next = [q, ...readRecent().filter((r) => querySignature(r) !== sig)].slice(0, RECENT_LIMIT);
  writeList(RECENT_KEY, next);
  return next;
}

export function clearRecent(): RetrievalQuery[] {
  writeList<RetrievalQuery>(RECENT_KEY, []);
  return [];
}
