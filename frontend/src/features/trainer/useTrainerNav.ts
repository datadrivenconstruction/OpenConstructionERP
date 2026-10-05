// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The menu a learner sees while an Academy course is active.
//
// The sidebar renders this model; it does not decide anything about the
// course itself. The model holds:
//   - the Course map row;
//   - "Open modules": the course's always-open modules plus every lock the
//     course has opened, as catalogue rows (label key, icon, route);
//   - "Opens as you go": the locks still closed, each with the task that opens
//     it;
//   - the footnote "The rest of the platform opens in later courses" when the
//     course hides everything outside it;
//   - `hidesFromCatalogue(to)`, which the normal group loop, Pinned and the
//     module counter use to keep locked and already-listed rows out.
//
// View mode (decision 3). The frontend view-mode rule wins: Academy rows never
// carry `advancedOnly`, the groups they come from may be `hideInSimple`
// (Bid Management in Procurement, Variations in Change), and the section shows
// them anyway once the course opens them. Nothing here reads or writes the
// user's view mode, so Advanced mode cannot reveal a locked module either:
// locked rows are filtered by `hidesFromCatalogue`, which ignores the mode.
//
// Trainer off (not an academy box, or no enrolment): the hook returns null and
// the sidebar is exactly what it was before the trainer existed.

import { useMemo } from 'react';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { Map as MapIcon, Percent } from 'lucide-react';

import { LEARN_GROUP_ID, navGroups, type NavGroup, type NavItem } from '@/app/layout/navCatalog';

import { courseLocaleOf } from './courseLocale';
import { isBadgeLockId, type LockRegistryEntry } from './lockRegistry';
import { COURSE_MAP_ROUTE, normalizePath } from './routeMatch';
import type { OutsideCourse, TrainerMe, UnlockInfo } from './types';
import { useTrainerMode, type TrainerModeState } from './useTrainerMode';

// Re-exported for useTrainerNav.test.tsx; defined once in routeMatch.ts.
export { COURSE_MAP_ROUTE };

// ── Where each lock lives in the menu ───────────────────────────────────────

/**
 * Where the Academy row for a lock points.
 *
 * - `catalogue`: the lock stands for a navCatalog row. With `query`, the row is
 *   a tab of that screen (`/contracts?tab=claims`) and stands for the tab, not
 *   the whole row, so the row itself is left to the out-of-course policy.
 * - `panel`: the lock is a panel inside a page. The row links to the page that
 *   holds the panel and scrolls to `anchor`; `hostRow` is the catalogue row of
 *   that page, used for the module gate.
 */
export type LockNavTarget =
  | { via: 'catalogue'; row: string; query?: string }
  | { via: 'panel'; anchor: string; hostRow: string };

/**
 * Every fixed lock id and the one catalogue row or panel anchor it maps to.
 * `lockNavProblems` checks this table against `LOCK_REGISTRY` and `navGroups`
 * (design R15); change all three together.
 *
 * `contracts.progress_claims` carries neither a catalogue row nor a panel
 * anchor in the registry: it is the claims tab, gated inside ContractsPage, so
 * its row opens `/contracts?tab=claims`.
 */
export const LOCK_NAV: Readonly<Record<string, LockNavTarget>> = {
  'boq.markups_panel': { via: 'panel', anchor: 'boq-markups-panel', hostRow: '/boq' },
  bid_management: { via: 'catalogue', row: '/bid-management' },
  'contracts.progress_claims': { via: 'catalogue', row: '/contracts', query: '?tab=claims' },
  contracts: { via: 'catalogue', row: '/contracts' },
  variations: { via: 'catalogue', row: '/variations' },
};

function catalogueRows(groups: readonly NavGroup[]): NavItem[] {
  return groups.flatMap((g) => g.items);
}

/**
 * What is wrong between the lock registry, the nav table and the catalogue.
 * Empty when every lock maps to exactly one catalogue row or panel anchor.
 * Pure, so the parity test can feed it a catalogue with a row removed.
 */
export function lockNavProblems(
  registry: readonly LockRegistryEntry[],
  groups: readonly NavGroup[],
  table: Readonly<Record<string, LockNavTarget>> = LOCK_NAV,
): string[] {
  const problems: string[] = [];
  const rows = catalogueRows(groups);
  const countRow = (to: string) => rows.filter((r) => r.to === to).length;
  const ids = new Set(registry.map((e) => e.lockId));

  for (const id of Object.keys(table)) {
    if (!ids.has(id)) problems.push(`${id}: in the nav table but not in the lock registry`);
  }
  for (const entry of registry) {
    const target = table[entry.lockId];
    if (!target) {
      problems.push(`${entry.lockId}: no catalogue row or panel anchor in the nav table`);
      continue;
    }
    if (target.via === 'catalogue') {
      const n = countRow(target.row);
      if (n !== 1) problems.push(`${entry.lockId}: catalogue row ${target.row} found ${n} times, expected 1`);
      if (entry.panelAnchor !== null) {
        problems.push(`${entry.lockId}: the registry names panel ${entry.panelAnchor}, the nav table a catalogue row`);
      }
      if (entry.catalogueRow !== null && (entry.catalogueRow !== target.row || target.query)) {
        problems.push(`${entry.lockId}: the registry hides ${entry.catalogueRow}, the nav table opens ${target.row}${target.query ?? ''}`);
      }
      if (entry.kind === 'module' && target.query) {
        problems.push(`${entry.lockId}: a module lock stands for a whole row, not a tab`);
      }
      if (entry.kind === 'tab' && !target.query) {
        problems.push(`${entry.lockId}: a tab lock must open its tab, not the whole row`);
      }
      if (entry.kind === 'panel') problems.push(`${entry.lockId}: a panel lock must map to a panel anchor`);
    } else {
      const n = countRow(target.hostRow);
      if (n !== 1) problems.push(`${entry.lockId}: host row ${target.hostRow} found ${n} times, expected 1`);
      if (entry.catalogueRow !== null) {
        problems.push(`${entry.lockId}: the registry hides ${entry.catalogueRow}, the nav table names a panel`);
      }
      if (entry.panelAnchor !== target.anchor) {
        problems.push(`${entry.lockId}: the registry anchor ${entry.panelAnchor} differs from ${target.anchor}`);
      }
      if (entry.kind !== 'panel') problems.push(`${entry.lockId}: only a panel lock maps to a panel anchor`);
    }
  }
  return problems;
}

// ── The model ───────────────────────────────────────────────────────────────

/**
 * One Academy row. It is a `NavItem`, so the sidebar can hand it to its row
 * component and its gates (`passesRowGates`) unchanged, with a few extras.
 *
 * Label: a catalogue row keeps `labelKey`/`defaultLabel` and the sidebar
 * resolves it as it does every row. A row the course names (an unlocked or
 * locked lock) also carries `courseLabel`, the course's own `opens_label` in
 * the course language; render it inside `lang={contentLang}`.
 *
 * Never set on a row: `advancedOnly` (decision 3) and `tourId` (the catalogue
 * row keeps the tour anchor).
 */
export interface TrainerNavRow extends NavItem {
  /** Stable key for React lists. */
  id: string;
  kind: 'course_map' | 'open' | 'locked';
  /** The lock this row stands for; null for the course map and always-open rows. */
  lockId: string | null;
  /** The navCatalog row this row stands for, when it stands for a whole row. */
  catalogueRow: string | null;
  courseLabel?: string;
  contentLang?: string;
  locked: boolean;
  /** Pre-translated "After task 3", shown in place of the shortcut column. */
  lockHint?: string;
  /** Pre-translated accessible name of a locked row ("Variations, opens after task 4"). */
  ariaLabelOverride?: string;
  /** The task that opens this row's lock. */
  openedByTask: number | null;
  /** Opened and not yet seen by the learner: the row shows a "New" chip. */
  fresh: boolean;
}

export interface TrainerNavCourse {
  title: string;
  /** BCP 47 locale of the course text, for `lang` on the title and course labels. */
  lang: string;
  done: number;
  total: number;
}

/**
 * - `ready`: an enrolment is loaded; every list is filled.
 * - `pending`: the academy flag is on (live or cached) and `/me` has not
 *   answered. Only the course map row; the catalogue stays hidden so a
 *   returning learner never sees the full menu flash.
 * - `error`: `/me` failed. Only the course map row (whose page shows the
 *   error and Retry); the catalogue fails open, as the locks do.
 */
export type TrainerNavStatus = 'ready' | 'pending' | 'error';

export interface TrainerNav {
  status: TrainerNavStatus;
  /** Null unless `ready`. */
  course: TrainerNavCourse | null;
  courseMap: TrainerNavRow;
  openRows: TrainerNavRow[];
  lockedRows: TrainerNavRow[];
  /** Every row in render order: course map, open, locked. */
  rows: TrainerNavRow[];
  outsideCourse: OutsideCourse | null;
  /** Pre-translated footnote, set only when the course hides the rest of the platform. */
  footnote: string | null;
  /**
   * True when the normal menu (groups, Pinned, workspace, counter) must not
   * show the catalogue row `to`: a locked module, a row the Academy section
   * already lists, or, under `outside_course: 'hidden'`, anything outside the
   * course. Learn rows and the course map are never hidden.
   */
  hidesFromCatalogue: (to: string) => boolean;
}

const ROW_BY_TO: ReadonlyMap<string, NavItem> = (() => {
  const map = new Map<string, NavItem>();
  for (const item of catalogueRows(navGroups)) if (!map.has(item.to)) map.set(item.to, item);
  return map;
})();

const NEVER_HIDDEN: ReadonlySet<string> = new Set([
  normalizePath(COURSE_MAP_ROUTE),
  ...(navGroups.find((g) => g.id === LEARN_GROUP_ID)?.items ?? []).map((i) => normalizePath(i.to)),
]);

/** A catalogue row copied field by field, so `advancedOnly` and `tourId` never travel. */
function fromCatalogue(item: NavItem, to: string = item.to): NavItem {
  const row: NavItem = { labelKey: item.labelKey, to, icon: item.icon };
  if (item.defaultLabel !== undefined) row.defaultLabel = item.defaultLabel;
  if (item.moduleKey !== undefined) row.moduleKey = item.moduleKey;
  if (item.helpKey !== undefined) row.helpKey = item.helpKey;
  if (item.defaultHelp !== undefined) row.defaultHelp = item.defaultHelp;
  if (item.badge !== undefined) row.badge = item.badge;
  if (item.roleGate !== undefined) row.roleGate = item.roleGate;
  if (item.adminOnly !== undefined) row.adminOnly = item.adminOnly;
  return row;
}

/** The catalogue row an `always_open` key names (`projects` -> `/projects`), or null. */
export function catalogueRowForModuleKey(key: string): NavItem | null {
  const slug = key.trim().toLowerCase();
  if (!slug) return null;
  const candidates = [`/${slug}`, `/${slug.replace(/_/g, '-')}`];
  for (const to of candidates) {
    const row = ROW_BY_TO.get(to);
    if (row) return row;
  }
  for (const row of ROW_BY_TO.values()) if (row.moduleKey === slug) return row;
  return null;
}

/**
 * "New" chip rule, kept in one place: the lock is open and the learner has not
 * seen it yet (`seen` is the only server signal; the unlock dialog posts it).
 */
export function isFreshUnlock(unlock: Pick<UnlockInfo, 'state' | 'seen'> | undefined): boolean {
  return unlock !== undefined && unlock.state === 'open' && !unlock.seen;
}

function courseMapRow(): TrainerNavRow {
  return {
    id: 'course-map',
    kind: 'course_map',
    labelKey: 'trainer.nav.course_map',
    defaultLabel: 'Course map',
    to: COURSE_MAP_ROUTE,
    icon: MapIcon,
    lockId: null,
    catalogueRow: null,
    locked: false,
    openedByTask: null,
    fresh: false,
  };
}

/** The page that holds a panel lock: the task that works in the panel, else the task that opens it. */
function panelRoute(me: TrainerMe, anchor: string, openedBy: number | null, hostRow: string): string {
  const inPanel = me.tasks.find((task) => task.target?.anchor === anchor && task.target.route);
  const opener = openedBy === null ? undefined : me.tasks.find((task) => task.n === openedBy);
  const route = inPanel?.target?.route ?? opener?.target?.route ?? hostRow;
  return `${route.split('#', 1)[0]}#${anchor}`;
}

function routeOnly(to: string): string {
  return normalizePath(to);
}

/** Pure builder behind `useTrainerNav` for an active enrolment. */
export function buildTrainerNav(me: TrainerMe, t: TFunction): TrainerNav {
  const lang = courseLocaleOf(me.course);
  const unlockById = new Map(me.unlocks.map((u) => [u.lock_id, u]));
  const openRows: TrainerNavRow[] = [];
  const lockedRows: TrainerNavRow[] = [];
  const usedTo = new Set<string>();

  for (const key of me.nav.always_open) {
    const item = catalogueRowForModuleKey(key);
    if (!item || usedTo.has(item.to)) continue;
    usedTo.add(item.to);
    openRows.push({
      ...fromCatalogue(item),
      id: `open:${item.to}`,
      kind: 'open',
      lockId: null,
      catalogueRow: item.to,
      locked: false,
      openedByTask: null,
      fresh: false,
    });
  }

  // Course order: one row per lock the course lists, by the task that opens it.
  const seenLocks = new Set<string>();
  const tasks = [...me.tasks].sort((a, b) => a.n - b.n);
  for (const task of tasks) {
    const lockId = task.opens;
    if (seenLocks.has(lockId) || isBadgeLockId(lockId)) continue;
    const target = LOCK_NAV[lockId];
    if (!target) continue;
    seenLocks.add(lockId);

    const unlock = unlockById.get(lockId);
    // A lock is closed only when `/me` says so; a listed lock with no unlock row is open.
    const locked = unlock?.state === 'locked';
    const openedByTask = unlock?.opened_by_task ?? task.n;
    const courseLabel = task.opens_label;

    let base: NavItem;
    let catalogueRow: string | null;
    if (target.via === 'catalogue') {
      const item = ROW_BY_TO.get(target.row);
      if (!item) continue;
      base = fromCatalogue(item, `${item.to}${target.query ?? ''}`);
      catalogueRow = target.query ? null : item.to;
    } else {
      const host = ROW_BY_TO.get(target.hostRow);
      if (!host) continue;
      base = { ...fromCatalogue(host, panelRoute(me, target.anchor, openedByTask, host.to)), icon: Percent };
      catalogueRow = null;
    }
    if (usedTo.has(base.to)) continue;
    usedTo.add(base.to);

    const row: TrainerNavRow = {
      ...base,
      id: `lock:${lockId}`,
      kind: locked ? 'locked' : 'open',
      lockId,
      catalogueRow,
      courseLabel,
      contentLang: lang,
      locked,
      openedByTask,
      fresh: !locked && isFreshUnlock(unlock),
    };
    if (locked) {
      row.lockHint = t('trainer.nav.after_task', { defaultValue: 'After task {{n}}', n: openedByTask });
      row.ariaLabelOverride = t('trainer.nav.locked_aria', {
        defaultValue: '{{label}}, opens after task {{n}}',
        label: courseLabel,
        n: openedByTask,
      });
      lockedRows.push(row);
    } else {
      openRows.push(row);
    }
  }

  // Open rows read: always-open modules as the course lists them, then opened
  // locks by task. Locked rows read by task.
  const courseMap = courseMapRow();
  const outside = me.nav.outside_course;

  const listed = new Set<string>();
  for (const row of openRows) {
    if (row.catalogueRow) listed.add(routeOnly(row.catalogueRow));
    // An opened tab stands in for its screen, so the screen's own row would
    // only repeat it.
    else if (row.lockId && LOCK_NAV[row.lockId]?.via === 'catalogue') listed.add(routeOnly(row.to));
  }
  const lockedModules = new Set(
    lockedRows.filter((r) => r.catalogueRow !== null).map((r) => routeOnly(r.catalogueRow as string)),
  );

  return {
    status: 'ready',
    course: { title: me.course.title, lang, done: me.progress.done, total: me.progress.total },
    courseMap,
    openRows,
    lockedRows,
    rows: [courseMap, ...openRows, ...lockedRows],
    outsideCourse: outside,
    footnote:
      outside === 'hidden'
        ? t('trainer.nav.rest_hidden', { defaultValue: 'The rest of the platform opens in later courses.' })
        : null,
    hidesFromCatalogue: (to: string) => {
      const path = routeOnly(to);
      if (NEVER_HIDDEN.has(path)) return false;
      // Every course row is listed in the Academy section or locked, so under
      // `hidden` nothing else of the catalogue remains.
      if (outside === 'hidden') return true;
      return listed.has(path) || lockedModules.has(path);
    },
  };
}

function placeholderNav(status: 'pending' | 'error'): TrainerNav {
  const courseMap = courseMapRow();
  return {
    status,
    course: null,
    courseMap,
    openRows: [],
    lockedRows: [],
    rows: [courseMap],
    outsideCourse: null,
    footnote: null,
    hidesFromCatalogue:
      status === 'pending' ? (to: string) => !NEVER_HIDDEN.has(routeOnly(to)) : () => false,
  };
}

/** The model for a trainer state, or null when the trainer is off. Pure. */
export function trainerNavFor(state: TrainerModeState, me: TrainerMe | null, t: TFunction): TrainerNav | null {
  switch (state) {
    case 'off':
    case 'none':
      return null;
    case 'checking':
    case 'loading':
      return placeholderNav('pending');
    case 'error':
      return placeholderNav('error');
    case 'enrolled':
      return me ? buildTrainerNav(me, t) : placeholderNav('pending');
    default:
      return null;
  }
}

/**
 * The Academy menu model, or null when the trainer is off (not an academy box,
 * signed out, or no enrolment). Reads `/me` through `useTrainerMode` only
 * (decision 33).
 */
export function useTrainerNav(): TrainerNav | null {
  const { state, me } = useTrainerMode();
  const { t } = useTranslation();
  return useMemo(() => trainerNavFor(state, me, t), [state, me, t]);
}
