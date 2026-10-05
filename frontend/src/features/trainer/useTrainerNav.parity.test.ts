// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Design R15: every lock id maps to exactly one catalogue row or panel anchor.
// This reads the real navCatalog objects, so a row renamed, moved twice or
// removed under the trainer fails here before the sidebar links to nothing.

import { describe, expect, it } from 'vitest';

import { navGroups, type NavGroup } from '@/app/layout/navCatalog';
import { meFixture } from './__fixtures__/me';
import { LOCK_REGISTRY, isBadgeLockId, type LockRegistryEntry } from './lockRegistry';
import { LOCK_NAV, lockNavProblems } from './useTrainerNav';

function withoutRow(groups: readonly NavGroup[], to: string): NavGroup[] {
  return groups.map((g) => ({ ...g, items: g.items.filter((i) => i.to !== to) }));
}

function withDuplicate(groups: readonly NavGroup[], to: string): NavGroup[] {
  const item = groups.flatMap((g) => g.items).find((i) => i.to === to);
  if (!item) throw new Error(`no row ${to}`);
  return [...groups, { id: 'grp_dup', labelKey: 'x', defaultOpen: true, items: [item] }];
}

describe('lock registry, nav table and catalogue agree', () => {
  it('has something to check (a wrong import would make every check vacuous)', () => {
    expect(LOCK_REGISTRY.length).toBeGreaterThanOrEqual(5);
    expect(navGroups.flatMap((g) => g.items).length).toBeGreaterThan(50);
  });

  it('every lock id maps to exactly one catalogue row or panel anchor', () => {
    expect(lockNavProblems(LOCK_REGISTRY, navGroups)).toEqual([]);
  });

  it('the nav table holds exactly the registry ids', () => {
    expect(Object.keys(LOCK_NAV).sort()).toEqual(LOCK_REGISTRY.map((e) => e.lockId).sort());
  });

  it('every non-badge lock the fixture course opens has a menu place', () => {
    const opens = meFixture.tasks.map((task) => task.opens).filter((id) => !isBadgeLockId(id));
    expect(opens.length).toBeGreaterThan(0);
    for (const id of opens) expect(LOCK_NAV[id], id).toBeDefined();
  });

  it('the markups panel lock never points at /markups (PDF drawing markups)', () => {
    expect(LOCK_NAV['boq.markups_panel']).toEqual({ via: 'panel', anchor: 'boq-markups-panel', hostRow: '/boq' });
  });
});

describe('the parity check fails when the catalogue changes under it', () => {
  it('a removed module row', () => {
    const problems = lockNavProblems(LOCK_REGISTRY, withoutRow(navGroups, '/variations'));
    expect(problems.some((p) => p.startsWith('variations:') && p.includes('found 0 times'))).toBe(true);
  });

  it('a removed panel host row', () => {
    const problems = lockNavProblems(LOCK_REGISTRY, withoutRow(navGroups, '/boq'));
    expect(problems.some((p) => p.startsWith('boq.markups_panel:'))).toBe(true);
  });

  it('a row listed twice', () => {
    const problems = lockNavProblems(LOCK_REGISTRY, withDuplicate(navGroups, '/bid-management'));
    expect(problems.some((p) => p.startsWith('bid_management:') && p.includes('found 2 times'))).toBe(true);
  });

  it('a lock added to the registry and not to the nav table', () => {
    const extra: LockRegistryEntry = {
      lockId: 'finance',
      kind: 'module',
      module: 'oe_finance',
      routes: ['/finance'],
      catalogueRow: '/finance',
      panelAnchor: null,
    };
    const problems = lockNavProblems([...LOCK_REGISTRY, extra], navGroups);
    expect(problems).toContain('finance: no catalogue row or panel anchor in the nav table');
  });

  it('a nav table entry with no lock behind it', () => {
    const problems = lockNavProblems(LOCK_REGISTRY, navGroups, { ...LOCK_NAV, tendering: { via: 'catalogue', row: '/tendering' } });
    expect(problems).toContain('tendering: in the nav table but not in the lock registry');
  });

  it('a registry row that disagrees with the nav table', () => {
    const moved = LOCK_REGISTRY.map((e) => (e.lockId === 'variations' ? { ...e, catalogueRow: '/changeorders' } : e));
    const problems = lockNavProblems(moved, navGroups);
    expect(problems.some((p) => p.startsWith('variations:') && p.includes('/changeorders'))).toBe(true);
  });

  it('a registry anchor that disagrees with the nav table', () => {
    const moved = LOCK_REGISTRY.map((e) => (e.lockId === 'boq.markups_panel' ? { ...e, panelAnchor: 'other' } : e));
    expect(lockNavProblems(moved, navGroups).some((p) => p.startsWith('boq.markups_panel:'))).toBe(true);
  });

  it('a module lock mapped to a tab, or a tab lock mapped to a whole row', () => {
    const asTab = lockNavProblems(LOCK_REGISTRY, navGroups, {
      ...LOCK_NAV,
      variations: { via: 'catalogue', row: '/variations', query: '?tab=x' },
    });
    expect(asTab.some((p) => p.startsWith('variations:'))).toBe(true);
    const asRow = lockNavProblems(LOCK_REGISTRY, navGroups, {
      ...LOCK_NAV,
      'contracts.progress_claims': { via: 'catalogue', row: '/contracts' },
    });
    expect(asRow.some((p) => p.startsWith('contracts.progress_claims:'))).toBe(true);
  });
});
