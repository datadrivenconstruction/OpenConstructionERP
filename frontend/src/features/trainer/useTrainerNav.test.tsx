// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import type { TFunction } from 'i18next';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { Percent } from 'lucide-react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: fakeT, i18n: { language: 'en', changeLanguage: vi.fn() } }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

const mode = vi.hoisted(() => ({
  current: { state: 'off', me: null } as { state: string; me: unknown },
}));
vi.mock('./useTrainerMode', () => ({
  useTrainerMode: () => ({
    state: mode.current.state,
    me: mode.current.me,
    academyMode: mode.current.state !== 'off',
    known: true,
    active: mode.current.state === 'enrolled',
    refetch: () => {},
  }),
}));

import { navGroups } from '@/app/layout/navCatalog';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { meFixture } from './__fixtures__/me';
import type { TaskSummary, TrainerMe, UnlockInfo } from './types';
import {
  COURSE_MAP_ROUTE,
  buildTrainerNav,
  catalogueRowForModuleKey,
  isFreshUnlock,
  trainerNavFor,
  useTrainerNav,
  type TrainerNavRow,
} from './useTrainerNav';

function fakeT(key: string, opts?: Record<string, unknown>): string {
  const template = typeof opts?.defaultValue === 'string' ? opts.defaultValue : key;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name] ?? ''));
}
const t = fakeT as unknown as TFunction;

function clone(): TrainerMe {
  return JSON.parse(JSON.stringify(meFixture)) as TrainerMe;
}

function withUnlock(me: TrainerMe, lockId: string, patch: Partial<UnlockInfo>): TrainerMe {
  me.unlocks = me.unlocks.map((u) => (u.lock_id === lockId ? { ...u, ...patch } : u));
  return me;
}

function open(me: TrainerMe, lockId: string, seen = false): TrainerMe {
  return withUnlock(me, lockId, { state: 'open', opened_at: '2026-10-06T10:00:00Z', seen });
}

const tos = (rows: TrainerNavRow[]) => rows.map((r) => r.to);

function groupOf(to: string) {
  return navGroups.find((g) => g.items.some((i) => i.to === to));
}

afterEach(() => {
  mode.current = { state: 'off', me: null };
});

describe('buildTrainerNav on the fixture course', () => {
  const nav = buildTrainerNav(meFixture, t);

  it('starts with the course map', () => {
    expect(nav.status).toBe('ready');
    expect(nav.courseMap.to).toBe(COURSE_MAP_ROUTE);
    expect(nav.courseMap.labelKey).toBe('trainer.nav.course_map');
    expect(nav.courseMap.defaultLabel).toBe('Course map');
    expect(nav.rows[0]).toBe(nav.courseMap);
  });

  it('carries the course name, its locale and the progress', () => {
    expect(nav.course).toEqual({
      title: meFixture.course.title,
      lang: 'en-GB',
      done: 1,
      total: 5,
    });
  });

  it('lists the always-open modules, then the opened markups panel', () => {
    expect(tos(nav.openRows)).toEqual([
      '/projects',
      '/boq',
      '/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b#boq-markups-panel',
    ]);
    const [projects, boq, markups] = nav.openRows as [TrainerNavRow, TrainerNavRow, TrainerNavRow];
    expect(projects.labelKey).toBe('projects.title');
    expect(boq.labelKey).toBe('boq.title');
    expect(projects.courseLabel).toBeUndefined();
    expect(markups.lockId).toBe('boq.markups_panel');
    expect(markups.courseLabel).toBe('Markups');
    expect(markups.contentLang).toBe('en-GB');
    expect(markups.icon).toBe(Percent);
    expect(markups.catalogueRow).toBeNull();
    // The fixture says the learner has seen it.
    expect(markups.fresh).toBe(false);
  });

  it('lists the closed locks by the task that opens them, with a real href', () => {
    expect(nav.lockedRows.map((r) => [r.lockId, r.to, r.openedByTask])).toEqual([
      ['bid_management', '/bid-management', 2],
      ['contracts.progress_claims', '/contracts?tab=claims', 3],
      ['variations', '/variations', 4],
    ]);
    for (const row of nav.lockedRows) {
      expect(row.locked).toBe(true);
      expect(row.kind).toBe('locked');
      expect(row.to).not.toBe('');
      expect(row.to).not.toBe('#');
      expect(row.lockHint).toBe(`After task ${row.openedByTask}`);
      expect(row.ariaLabelOverride).toBe(`${row.courseLabel}, opens after task ${row.openedByTask}`);
    }
    expect(nav.lockedRows[0]?.ariaLabelOverride).toBe('Bid Management, opens after task 2');
  });

  it('never makes a row for the badge', () => {
    expect(nav.rows.some((r) => (r.lockId ?? '').startsWith('badge:'))).toBe(false);
  });

  it('renders rows in course map, open, locked order with unique keys', () => {
    expect(nav.rows).toEqual([nav.courseMap, ...nav.openRows, ...nav.lockedRows]);
    expect(new Set(nav.rows.map((r) => r.id)).size).toBe(nav.rows.length);
  });

  it('shows the footnote when the course hides the rest of the platform', () => {
    expect(nav.outsideCourse).toBe('hidden');
    expect(nav.footnote).toBe('The rest of the platform opens in later courses.');
    const more = clone();
    more.nav.outside_course = 'more';
    expect(buildTrainerNav(more, t).footnote).toBeNull();
  });
});

describe('decision 3: the Academy section ignores the view mode', () => {
  it('rows from hideInSimple groups carry no mode flag once opened', () => {
    // The premise: these two rows are hidden in Simple mode by their group.
    expect(groupOf('/bid-management')?.hideInSimple).toBe(true);
    expect(groupOf('/variations')?.hideInSimple).toBe(true);

    let me = clone();
    me = open(me, 'bid_management');
    me = open(me, 'variations');
    const nav = buildTrainerNav(me, t);
    expect(tos(nav.openRows)).toEqual(expect.arrayContaining(['/bid-management', '/variations']));
    for (const row of nav.rows) {
      expect(row).not.toHaveProperty('advancedOnly');
      expect(row).not.toHaveProperty('tourId');
    }
  });

  it('keeps moduleKey and help text, so the sidebar module gate still applies', () => {
    const tendering = navGroups.flatMap((g) => g.items).find((i) => i.to === '/tendering');
    expect(tendering?.moduleKey).toBe('tendering');
    const row = catalogueRowForModuleKey('tendering');
    expect(row?.to).toBe('/tendering');
    const nav = buildTrainerNav(open(clone(), 'bid_management'), t);
    const bid = nav.openRows.find((r) => r.lockId === 'bid_management');
    expect(bid?.helpKey).toBe('sidebar.help.bid_management');
  });

  it('gives the same model in Simple and Advanced, and never writes the mode', () => {
    mode.current = { state: 'enrolled', me: meFixture };
    const setMode = vi.spyOn(useViewModeStore.getState(), 'setMode');
    useViewModeStore.setState({ mode: 'simple', isAdvanced: false });
    const simple = renderHook(() => useTrainerNav()).result.current;
    useViewModeStore.setState({ mode: 'advanced', isAdvanced: true });
    const advanced = renderHook(() => useTrainerNav()).result.current;
    expect(simple && tos(simple.rows)).toEqual(advanced && tos(advanced.rows));
    // Advanced mode cannot reveal a locked module.
    expect(advanced?.hidesFromCatalogue('/variations')).toBe(true);
    expect(setMode).not.toHaveBeenCalled();
    setMode.mockRestore();
  });
});

describe('opening locks', () => {
  it('moves an opened module to Open modules with a New chip until seen', () => {
    const nav = buildTrainerNav(open(clone(), 'bid_management'), t);
    const bid = nav.openRows.find((r) => r.lockId === 'bid_management');
    expect(bid).toMatchObject({ to: '/bid-management', locked: false, fresh: true, courseLabel: 'Bid Management' });
    expect(bid?.lockHint).toBeUndefined();
    expect(bid?.ariaLabelOverride).toBeUndefined();
    expect(nav.lockedRows.map((r) => r.lockId)).toEqual(['contracts.progress_claims', 'variations']);

    const seen = buildTrainerNav(open(clone(), 'bid_management', true), t);
    expect(seen.openRows.find((r) => r.lockId === 'bid_management')?.fresh).toBe(false);
  });

  it('the New rule is open and not seen, nothing else', () => {
    expect(isFreshUnlock({ state: 'open', seen: false })).toBe(true);
    expect(isFreshUnlock({ state: 'open', seen: true })).toBe(false);
    expect(isFreshUnlock({ state: 'locked', seen: false })).toBe(false);
    expect(isFreshUnlock(undefined)).toBe(false);
  });

  it('follows the course label, not the catalogue label (US: Change orders opens /variations)', () => {
    const me = clone();
    me.tasks = me.tasks.map((task) => (task.opens === 'variations' ? { ...task, opens_label: 'Change orders' } : task));
    const row = buildTrainerNav(me, t).lockedRows.find((r) => r.lockId === 'variations');
    expect(row?.to).toBe('/variations');
    expect(row?.courseLabel).toBe('Change orders');
    expect(row?.ariaLabelOverride).toBe('Change orders, opens after task 4');
  });

  it('a lock the course lists without an unlock row is open', () => {
    const me = clone();
    me.unlocks = me.unlocks.filter((u) => u.lock_id !== 'variations');
    const nav = buildTrainerNav(me, t);
    expect(nav.openRows.find((r) => r.lockId === 'variations')?.locked).toBe(false);
    expect(nav.lockedRows.some((r) => r.lockId === 'variations')).toBe(false);
  });

  it('an unlock the course does not list makes no row', () => {
    const me = clone();
    me.unlocks.push({
      lock_id: 'contracts',
      kind: 'module',
      state: 'locked',
      opened_by_task: 9,
      opened_at: null,
      seen: false,
      tiles: [],
    });
    const nav = buildTrainerNav(me, t);
    expect(nav.rows.some((r) => r.lockId === 'contracts')).toBe(false);
    expect(nav.rows.some((r) => r.to === '/contracts')).toBe(false);
  });

  it('skips an unknown lock id and an unknown always-open key without failing', () => {
    const me = clone();
    me.tasks = [...me.tasks, { ...me.tasks[4], id: 't6-x', n: 6, opens: 'not_a_lock', opens_label: 'X' } as TaskSummary];
    me.nav.always_open = ['projects', 'no_such_module', 'boq'];
    const nav = buildTrainerNav(me, t);
    expect(nav.rows.some((r) => r.lockId === 'not_a_lock')).toBe(false);
    expect(tos(nav.openRows).slice(0, 2)).toEqual(['/projects', '/boq']);
  });

  it('maps always-open keys to catalogue rows, with underscores as hyphens', () => {
    expect(catalogueRowForModuleKey('projects')?.to).toBe('/projects');
    expect(catalogueRowForModuleKey('BOQ')?.to).toBe('/boq');
    expect(catalogueRowForModuleKey('bid_management')?.to).toBe('/bid-management');
    expect(catalogueRowForModuleKey('')).toBeNull();
    expect(catalogueRowForModuleKey('no_such_module')).toBeNull();
  });

  it('does not list a row twice when an always-open key names a course module', () => {
    const me = open(clone(), 'bid_management');
    me.nav.always_open = ['projects', 'boq', 'bid_management'];
    const nav = buildTrainerNav(me, t);
    expect(nav.rows.filter((r) => r.to === '/bid-management')).toHaveLength(1);
  });

  it('points the markups row at the task that opens it when no task names the anchor', () => {
    const me = clone();
    me.tasks = me.tasks.map((task) => (task.target ? { ...task, target: { ...task.target, anchor: null } } : task));
    const row = buildTrainerNav(me, t).openRows.find((r) => r.lockId === 'boq.markups_panel');
    expect(row?.to).toBe('/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b#boq-markups-panel');

    me.tasks = me.tasks.map((task) => ({ ...task, target: null }));
    const bare = buildTrainerNav(me, t).openRows.find((r) => r.lockId === 'boq.markups_panel');
    expect(bare?.to).toBe('/boq#boq-markups-panel');
  });

  it('shows a closed markups panel among the locked rows, still linking to the BOQ', () => {
    const me = withUnlock(clone(), 'boq.markups_panel', { state: 'locked', opened_at: null, seen: false });
    const row = buildTrainerNav(me, t).lockedRows[0] as TrainerNavRow;
    expect(row.lockId).toBe('boq.markups_panel');
    expect(row.to).toContain('#boq-markups-panel');
    expect(row.lockHint).toBe('After task 1');
  });
});

describe('hidesFromCatalogue', () => {
  it('under "hidden" keeps only the Learn rows and the course map', () => {
    const nav = buildTrainerNav(meFixture, t);
    for (const to of ['/dashboard', '/projects', '/boq', '/bid-management', '/variations', '/contracts', '/markups', '/templates']) {
      expect(nav.hidesFromCatalogue(to), to).toBe(true);
    }
    for (const to of ['/videos', '/cases', '/academy', '/Videos/']) {
      expect(nav.hidesFromCatalogue(to), to).toBe(false);
    }
  });

  it('under "more" hides locked modules and listed rows, and shows the rest', () => {
    const me = clone();
    me.nav.outside_course = 'more';
    const nav = buildTrainerNav(me, t);
    // Locked modules.
    expect(nav.hidesFromCatalogue('/bid-management')).toBe(true);
    expect(nav.hidesFromCatalogue('/variations')).toBe(true);
    // Already in the Academy section.
    expect(nav.hidesFromCatalogue('/projects')).toBe(true);
    expect(nav.hidesFromCatalogue('/boq')).toBe(true);
    // A closed tab does not hide its screen.
    expect(nav.hidesFromCatalogue('/contracts')).toBe(false);
    // /markups is the PDF markups module, not the BOQ markups panel.
    expect(nav.hidesFromCatalogue('/markups')).toBe(false);
    // Outside the course.
    expect(nav.hidesFromCatalogue('/dashboard')).toBe(false);
    expect(nav.hidesFromCatalogue('/templates')).toBe(false);
    expect(nav.hidesFromCatalogue('/videos')).toBe(false);
  });

  it('under "more" an opened module or tab hides its catalogue row, which the section lists', () => {
    let me = clone();
    me.nav.outside_course = 'more';
    me = open(me, 'bid_management');
    me = open(me, 'contracts.progress_claims');
    const nav = buildTrainerNav(me, t);
    expect(nav.hidesFromCatalogue('/bid-management')).toBe(true);
    expect(nav.hidesFromCatalogue('/contracts')).toBe(true);
    expect(nav.openRows.find((r) => r.lockId === 'contracts.progress_claims')?.to).toBe('/contracts?tab=claims');
  });

  it('a course that locks the whole contracts module hides /contracts (FR)', () => {
    const me = clone();
    me.nav.outside_course = 'more';
    me.tasks = me.tasks.map((task) =>
      task.opens === 'contracts.progress_claims' ? { ...task, opens: 'contracts', opens_label: 'Contrats' } : task,
    );
    me.unlocks = me.unlocks.map((u) =>
      u.lock_id === 'contracts.progress_claims' ? { ...u, lock_id: 'contracts', kind: 'module' } : u,
    );
    const nav = buildTrainerNav(me, t);
    const row = nav.lockedRows.find((r) => r.lockId === 'contracts');
    expect(row?.to).toBe('/contracts');
    expect(row?.catalogueRow).toBe('/contracts');
    expect(nav.hidesFromCatalogue('/contracts')).toBe(true);
  });
});

describe('trainerNavFor: the trainer states', () => {
  it('off and no enrolment give null: the sidebar is unchanged', () => {
    expect(trainerNavFor('off', null, t)).toBeNull();
    expect(trainerNavFor('none', null, t)).toBeNull();
  });

  it('while the course loads, only the course map, and the catalogue stays hidden (no flash)', () => {
    for (const state of ['checking', 'loading'] as const) {
      const nav = trainerNavFor(state, null, t);
      expect(nav?.status).toBe('pending');
      expect(nav?.rows.map((r) => r.id)).toEqual(['course-map']);
      expect(nav?.course).toBeNull();
      expect(nav?.footnote).toBeNull();
      expect(nav?.hidesFromCatalogue('/dashboard')).toBe(true);
      expect(nav?.hidesFromCatalogue('/videos')).toBe(false);
      expect(nav?.hidesFromCatalogue('/academy')).toBe(false);
    }
  });

  it('a failed /me keeps the course map and fails the catalogue open', () => {
    const nav = trainerNavFor('error', null, t);
    expect(nav?.status).toBe('error');
    expect(nav?.rows.map((r) => r.id)).toEqual(['course-map']);
    expect(nav?.hidesFromCatalogue('/dashboard')).toBe(false);
    expect(nav?.hidesFromCatalogue('/variations')).toBe(false);
  });

  it('an enrolment gives the full model', () => {
    expect(trainerNavFor('enrolled', meFixture, t)?.status).toBe('ready');
  });
});

describe('useTrainerNav', () => {
  beforeEach(() => {
    mode.current = { state: 'off', me: null };
  });

  it('returns null with the trainer off', () => {
    const { result } = renderHook(() => useTrainerNav());
    expect(result.current).toBeNull();
  });

  it('returns null on an academy box without an enrolment', () => {
    mode.current = { state: 'none', me: null };
    expect(renderHook(() => useTrainerNav()).result.current).toBeNull();
  });

  it('returns the course model for an enrolled learner, stable across renders', () => {
    mode.current = { state: 'enrolled', me: meFixture };
    const { result, rerender } = renderHook(() => useTrainerNav());
    const first = result.current;
    expect(first?.status).toBe('ready');
    expect(first?.lockedRows).toHaveLength(3);
    rerender();
    expect(result.current).toBe(first);
  });
});
