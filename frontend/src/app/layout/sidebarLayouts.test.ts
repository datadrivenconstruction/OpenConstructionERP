// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPut: vi.fn() }));
vi.mock('@/shared/lib/api', () => api);

import {
  MAX_LAYOUTS,
  MAX_LAYOUT_NAME,
  addLayout,
  layoutMatches,
  removeLayout,
  renameLayout,
  sanitizeLayoutData,
  sanitizeLayouts,
  validateLayoutName,
  type SidebarLayout,
  type SidebarLayoutData,
} from './sidebarLayouts';
import { menuLayoutReducer, DEFAULT_MENU_LAYOUT } from './menuLayout';
import { useSidebarLayoutsStore } from './useSidebarLayoutsStore';

const data = (over: Partial<SidebarLayoutData> = {}): SidebarLayoutData => ({
  ...sanitizeLayoutData({}),
  ...over,
});
const make = (n: number): SidebarLayout[] =>
  Array.from({ length: n }, (_, i) => ({ id: `id${i}`, name: `Layout ${i}`, data: data() }));

describe('validateLayoutName', () => {
  it('rejects empty and blank names', () => {
    expect(validateLayoutName('', [])).toBe('empty');
    expect(validateLayoutName('   ', [])).toBe('empty');
  });

  it('allows exactly 60 characters and rejects 61', () => {
    expect(validateLayoutName('x'.repeat(MAX_LAYOUT_NAME), [])).toBeNull();
    expect(validateLayoutName('x'.repeat(MAX_LAYOUT_NAME + 1), [])).toBe('too_long');
  });

  it('keeps names unique per user, ignoring case and spacing', () => {
    const list = make(2);
    expect(validateLayoutName('  layout   0 ', list)).toBe('taken');
    expect(validateLayoutName('Layout 0', list, 'id0')).toBeNull();
    expect(validateLayoutName('Layout 1', list, 'id0')).toBe('taken');
  });

  it('caps the list at 20 but still lets one be renamed', () => {
    expect(validateLayoutName('New', make(MAX_LAYOUTS - 1))).toBeNull();
    expect(validateLayoutName('New', make(MAX_LAYOUTS))).toBe('limit');
    expect(validateLayoutName('Renamed', make(MAX_LAYOUTS), 'id0')).toBeNull();
  });
});

describe('list operations', () => {
  it('adds, renames and removes', () => {
    let list = addLayout([], '  Site  week ', data({ pinned: ['/rfi'] }), 'a');
    expect(list).toEqual([{ id: 'a', name: 'Site week', data: data({ pinned: ['/rfi'] }) }]);
    list = renameLayout(list, 'a', 'Office');
    expect(list[0]?.name).toBe('Office');
    expect(removeLayout(list, 'a')).toEqual([]);
  });
});

describe('sanitize', () => {
  it('turns junk into a complete layout', () => {
    const d = sanitizeLayoutData({ hiddenModules: ['/a', 3], viewMode: 'weird', menu: { activeMode: 'nope' } });
    expect(d.hiddenModules).toEqual(['/a']);
    expect(d.viewMode).toBe('simple');
    expect(d.menu.activeMode).toBe('all');
    expect(sanitizeLayouts([{ id: 1 }, null, { id: 'ok', name: 'N', data: {} }]).map((l) => l.id)).toEqual(['ok']);
  });

  it('compares layouts ignoring the order of hidden rows', () => {
    expect(layoutMatches(data({ hiddenModules: ['/a', '/b'] }), data({ hiddenModules: ['/b', '/a'] }))).toBe(true);
    expect(layoutMatches(data({ pinned: ['/a', '/b'] }), data({ pinned: ['/b', '/a'] }))).toBe(false);
    expect(layoutMatches(data({ viewMode: 'advanced' }), data())).toBe(false);
  });
});

describe('replace action', () => {
  it('swaps the arrangement and keeps the rail style', () => {
    const state = { ...DEFAULT_MENU_LAYOUT, rail: 'icons' as const };
    const menu = { ...data().menu, groupOrder: ['g1'], activeMode: 'finance' as const };
    const next = menuLayoutReducer(state, { type: 'replace', menu });
    expect(next.groupOrder).toEqual(['g1']);
    expect(next.activeMode).toBe('finance');
    expect(next.rail).toBe('icons');
  });
});

describe('useSidebarLayoutsStore', () => {
  beforeEach(() => {
    api.apiGet.mockReset();
    api.apiPut.mockReset();
    api.apiPut.mockImplementation(async (_p: string, body: { layouts: SidebarLayout[] }) => body);
    useSidebarLayoutsStore.getState().clear();
  });

  it('loads the list from the server', async () => {
    api.apiGet.mockResolvedValue({ layouts: [{ id: 'a', name: 'Saved', data: {} }] });
    await useSidebarLayoutsStore.getState().load();
    expect(useSidebarLayoutsStore.getState().layouts.map((l) => l.name)).toEqual(['Saved']);
  });

  it('saves under a name, writes the whole list and refuses a duplicate', async () => {
    const first = await useSidebarLayoutsStore.getState().save('Estimating', data({ hiddenModules: ['/rfi'] }));
    expect(first.ok).toBe(true);
    expect(api.apiPut).toHaveBeenCalledTimes(1);
    const again = await useSidebarLayoutsStore.getState().save('estimating', data());
    expect(again).toEqual({ ok: false, error: 'taken' });
    expect(api.apiPut).toHaveBeenCalledTimes(1);
  });

  it('rolls back when the server refuses', async () => {
    await useSidebarLayoutsStore.getState().save('One', data());
    api.apiPut.mockRejectedValueOnce(new Error('422'));
    const res = await useSidebarLayoutsStore.getState().save('Two', data());
    expect(res).toEqual({ ok: false, error: 'save_failed' });
    expect(useSidebarLayoutsStore.getState().layouts.map((l) => l.name)).toEqual(['One']);
  });

  it('renames and deletes', async () => {
    const saved = await useSidebarLayoutsStore.getState().save('One', data());
    if (!saved.ok) throw new Error('save failed');
    await useSidebarLayoutsStore.getState().rename(saved.id, 'Uno');
    expect(useSidebarLayoutsStore.getState().layouts[0]?.name).toBe('Uno');
    await useSidebarLayoutsStore.getState().remove(saved.id);
    expect(useSidebarLayoutsStore.getState().layouts).toEqual([]);
  });
});
