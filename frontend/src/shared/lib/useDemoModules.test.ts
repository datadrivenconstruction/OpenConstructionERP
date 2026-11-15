// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { navGroups } from '@/app/layout/navCatalog';
import { DEMO_PROFILES, type DemoProfile } from './demoProfiles';
import { DEMO_ALWAYS_ROUTES, demoModulesFor, demoSectionCount, isRowInDemo } from './useDemoModules';

const base = DEMO_PROFILES[1]!;
const profile = (over: Partial<DemoProfile>): DemoProfile => ({ ...base, ...over });
const routesOf = (id: string) => navGroups.find((g) => g.id === id)!.items.map((i) => i.to);

describe('demo module list', () => {
  it('is every row of the listed groups, in menu order', () => {
    const list = demoModulesFor(profile({ groups: ['grp_handover', 'grp_takeoff'] }))!;
    expect(list).toEqual([...routesOf('grp_takeoff'), ...routesOf('grp_handover')]);
  });

  it('reads an alias id as the group that holds its rows', () => {
    const list = demoModulesFor(profile({ groups: ['grp_assistant'] }))!;
    expect(list).toEqual(routesOf('grp_automation_ai'));
    expect(list).toContain('/chat');
  });

  it('shows the whole menu when neither list is given', () => {
    expect(demoModulesFor(profile({ groups: null }))).toBeNull();
    expect(demoModulesFor(undefined)).toBeNull();
  });
});

describe('a row in a demo', () => {
  const set = new Set(['/boq', 'schedule', '/takeoff']);

  it('matches by route, by path without the query, and by module key', () => {
    expect(isRowInDemo({ to: '/boq' }, set)).toBe(true);
    expect(isRowInDemo({ to: '/takeoff?tab=measurements' }, set)).toBe(true);
    expect(isRowInDemo({ to: '/schedule', moduleKey: 'schedule' }, set)).toBe(true);
    expect(isRowInDemo({ to: '/safety' }, set)).toBe(false);
  });

  it('always keeps home, projects and the Learn card', () => {
    for (const route of ['/', '/projects', '/packs', '/videos']) {
      expect(DEMO_ALWAYS_ROUTES.has(route), route).toBe(true);
      expect(isRowInDemo({ to: route }, new Set()), route).toBe(true);
    }
    expect(DEMO_ALWAYS_ROUTES.has('/chat')).toBe(false);
  });
});

describe('menu sections a demo card advertises', () => {
  it('counts the groups with at least one demo row, out of the working groups', () => {
    const p = profile({ groups: ['grp_overview', 'grp_takeoff', 'grp_safety'] });
    const rows = new Set(demoModulesFor(p)!);
    const expected = navGroups
      .filter((g) => g.id !== 'grp_learn')
      .filter((g) => g.items.some((i) => !DEMO_ALWAYS_ROUTES.has(i.to.split('?')[0]!) && isRowInDemo(i, rows))).length;
    // A row listed in two groups lights both.
    expect(expected).toBeGreaterThanOrEqual(3);
    expect(demoSectionCount(p)).toEqual({ shown: expected, total: navGroups.length - 1 });
  });

  it('counts every group for the full platform', () => {
    const { shown, total } = demoSectionCount(DEMO_PROFILES[0]!);
    expect(shown).toBe(total);
  });
});
