// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Which lock a route belongs to.
//
// Matching rules (frontend design §3):
// 1. The query string and the hash are ignored. Tabs are gated by panel gates,
//    never by a URL lock.
// 2. A leading `/projects/:id` is stripped from both the path and the pattern,
//    so `/variations` and `/projects/p1/variations` are one module. The
//    project list `/projects` and a bare `/projects/:id` are left alone.
// 3. A pattern matches the path exactly or as a whole-segment prefix:
//    `/variations` matches `/variations/x`, never `/variations-foo`.
// 4. Case-insensitive, because the router is (react-router's `caseSensitive`
//    defaults to false and App.tsx never sets it).
//
// Whether a matched lock is CLOSED is a separate question answered by `/me`:
// a lock is closed only when the course lists it and its unlock says
// `state: 'locked'`. A lock the course does not list is open, and a route
// outside the course is never locked, whatever `nav.outside_course` says
// (founder Q1: out-of-course modules leave the menu, they are not locked).

import { LOCK_REGISTRY, getLock } from './lockRegistry';
import type { TrainerMe } from './types';

const PROJECT_PREFIX = /^\/projects\/[^/]+(?=\/.)/;

/** Path only, lower-cased, no query or hash, no duplicate or trailing slashes. */
export function normalizePath(pathOrUrl: string): string {
  const cut = pathOrUrl.split(/[?#]/, 1)[0] ?? '';
  const collapsed = cut.replace(/\/{2,}/g, '/').toLowerCase();
  const leading = collapsed.startsWith('/') ? collapsed : `/${collapsed}`;
  return leading.length > 1 ? leading.replace(/\/+$/, '') : leading;
}

/** `/projects/p1/variations` -> `/variations`. `/projects` and `/projects/p1` stay. */
export function stripProjectPrefix(path: string): string {
  return path.replace(PROJECT_PREFIX, '');
}

function segments(path: string): string[] {
  return path.split('/').filter((s) => s.length > 0);
}

/**
 * True when `pattern` (an App.tsx route path, `:params` allowed) matches
 * `pathname` exactly or as a whole-segment prefix, after the project prefix
 * is stripped from both.
 */
export function matchesRoutePattern(pathname: string, pattern: string): boolean {
  const path = segments(stripProjectPrefix(normalizePath(pathname)));
  const pat = segments(stripProjectPrefix(normalizePath(pattern)));
  if (pat.length === 0 || pat.length > path.length) return false;
  return pat.every((p, i) => p.startsWith(':') || p === path[i]);
}

function specificity(pattern: string): number {
  return segments(stripProjectPrefix(normalizePath(pattern))).length;
}

/**
 * Every registered lock whose routes match `pathname`, most specific first.
 *
 * `/projects/p/contracts/claims/c` gives `['contracts.progress_claims',
 * 'contracts']`: a course that locks only one of them (FR locks `contracts`)
 * still finds its own.
 */
export function lockIdsForPath(pathname: string): string[] {
  const hits: Array<{ lockId: string; score: number }> = [];
  for (const entry of LOCK_REGISTRY) {
    let best = -1;
    for (const route of entry.routes) {
      if (matchesRoutePattern(pathname, route)) best = Math.max(best, specificity(route));
    }
    if (best >= 0) hits.push({ lockId: entry.lockId, score: best });
  }
  // Stable sort keeps registry order between equally specific matches.
  return hits.sort((a, b) => b.score - a.score).map((h) => h.lockId);
}

/** The lock ids this enrolment holds closed right now. */
export function lockedLockIds(me: Pick<TrainerMe, 'unlocks'> | null | undefined): Set<string> {
  const closed = new Set<string>();
  for (const unlock of me?.unlocks ?? []) {
    if (unlock.state === 'locked') closed.add(unlock.lock_id);
  }
  return closed;
}

/**
 * The closed lock that gates `pathname`, or null when the route is open.
 * Picks the most specific matching lock that `/me` holds closed.
 */
export function closedLockForPath(pathname: string, me: Pick<TrainerMe, 'unlocks'> | null | undefined): string | null {
  const closed = lockedLockIds(me);
  if (closed.size === 0) return null;
  return lockIdsForPath(pathname).find((id) => closed.has(id)) ?? null;
}

/** The lock whose catalogue row is `to` (a navCatalog `to`), or null. */
export function lockIdForCatalogueRow(to: string): string | null {
  const path = normalizePath(to);
  return LOCK_REGISTRY.find((e) => e.catalogueRow !== null && normalizePath(e.catalogueRow) === path)?.lockId ?? null;
}

/** The panel anchor id a `panel` lock replaces, or null. */
export function panelAnchorFor(lockId: string): string | null {
  return getLock(lockId)?.panelAnchor ?? null;
}
