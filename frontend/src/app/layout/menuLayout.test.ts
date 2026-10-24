import { describe, expect, it } from 'vitest';
import {
  DEFAULT_MENU_LAYOUT,
  DEFAULT_MODE_ITEMS,
  applyOrder,
  menuLayoutReducer,
  modeItems,
  moveInList,
  resolveMenuLayout,
  sanitizeMenuLayout,
} from './menuLayout';
import { navGroups } from './navCatalog';
import { bottomNavRoutes } from './MenuBottomNav';

const routes = new Set(navGroups.flatMap((g) => g.items.map((i) => i.to)));

describe('menu layout reducer', () => {
  it('moves rows and clamps out-of-range targets', () => {
    expect(moveInList(['a', 'b', 'c'], 0, 2)).toEqual(['b', 'c', 'a']);
    expect(moveInList(['a', 'b', 'c'], 2, 9)).toEqual(['a', 'b', 'c']);
    expect(moveInList(['a', 'b'], 5, 0)).toEqual(['a', 'b']);
  });

  it('stores item order per group and applies it, unknown rows last', () => {
    const s = menuLayoutReducer(DEFAULT_MENU_LAYOUT, {
      type: 'moveItem', groupId: 'grp_x', current: ['/a', '/b', '/c'], from: 2, to: 0,
    });
    expect(s.order.grp_x).toEqual(['/c', '/a', '/b']);
    const items = ['/a', '/new', '/b', '/c'].map((to) => ({ to }));
    expect(applyOrder(items, s.order.grp_x, (i) => i.to).map((i) => i.to)).toEqual(['/c', '/a', '/b', '/new']);
  });

  it('reorders groups', () => {
    const s = menuLayoutReducer(DEFAULT_MENU_LAYOUT, { type: 'moveGroup', current: ['g1', 'g2', 'g3'], from: 0, to: 1 });
    expect(s.groupOrder).toEqual(['g2', 'g1', 'g3']);
  });

  it('creates, fills, reorders and removes a user group', () => {
    let s = menuLayoutReducer(DEFAULT_MENU_LAYOUT, { type: 'addUserGroup', id: 'day', label: '  My day ' });
    expect(s.userGroups).toEqual([{ id: 'day', label: 'My day', items: [] }]);
    expect(menuLayoutReducer(s, { type: 'addUserGroup', id: 'x', label: '   ' })).toBe(s);
    s = menuLayoutReducer(s, { type: 'toggleUserGroupItem', id: 'day', route: '/rfi' });
    s = menuLayoutReducer(s, { type: 'toggleUserGroupItem', id: 'day', route: '/tasks' });
    s = menuLayoutReducer(s, { type: 'moveItem', groupId: 'user:day', current: ['/rfi', '/tasks'], from: 1, to: 0 });
    expect(s.userGroups[0]!.items).toEqual(['/tasks', '/rfi']);
    s = menuLayoutReducer(s, { type: 'removeUserGroup', id: 'day' });
    expect(s.userGroups).toEqual([]);
  });

  it('reset clears the arrangement but keeps mode and sidebar style', () => {
    let s = menuLayoutReducer(DEFAULT_MENU_LAYOUT, { type: 'moveGroup', current: ['a', 'b'], from: 0, to: 1 });
    s = menuLayoutReducer(s, { type: 'setMode', mode: 'finance' });
    s = menuLayoutReducer(s, { type: 'setRail', rail: 'rail' });
    s = menuLayoutReducer(s, { type: 'reset' });
    expect(s.groupOrder).toEqual([]);
    expect(s.activeMode).toBe('finance');
    expect(s.rail).toBe('rail');
  });
});

describe('work modes', () => {
  it('every default mode has 8-12 real catalogue rows', () => {
    for (const [mode, list] of Object.entries(DEFAULT_MODE_ITEMS)) {
      expect(list.length, mode).toBeGreaterThanOrEqual(8);
      expect(list.length, mode).toBeLessThanOrEqual(12);
      for (const r of list) expect(routes.has(r), `${mode} ${r}`).toBe(true);
    }
  });

  it('All shows everything; modes are editable and resettable', () => {
    expect(modeItems(DEFAULT_MENU_LAYOUT, 'all')).toBeNull();
    let s = menuLayoutReducer(DEFAULT_MENU_LAYOUT, { type: 'toggleModeItem', mode: 'estimator', route: '/boq' });
    expect(modeItems(s, 'estimator')).not.toContain('/boq');
    s = menuLayoutReducer(s, { type: 'toggleModeItem', mode: 'estimator', route: '/rfi' });
    expect(modeItems(s, 'estimator')!.at(-1)).toBe('/rfi');
    s = menuLayoutReducer(s, { type: 'resetMode', mode: 'estimator' });
    expect(modeItems(s, 'estimator')).toEqual(DEFAULT_MODE_ITEMS.estimator);
  });

  it('bottom bar takes the first four rows of the mode', () => {
    expect(bottomNavRoutes(DEFAULT_MODE_ITEMS.site_manager)).toEqual(DEFAULT_MODE_ITEMS.site_manager.slice(0, 4));
  });
});

describe('serialised layout', () => {
  it('drops junk and lays user overrides over a company template', () => {
    expect(sanitizeMenuLayout({ rail: 'bogus', activeMode: 'chef', groupOrder: [1] })).toEqual({});
    const layout = resolveMenuLayout(
      { groupOrder: ['g2'], modes: { finance: ['/finance'] }, order: { g: ['/a'] } },
      { modes: { estimator: ['/boq'] }, activeMode: 'estimator' },
    );
    expect(layout.groupOrder).toEqual(['g2']);
    expect(layout.modes).toEqual({ finance: ['/finance'], estimator: ['/boq'] });
    expect(layout.activeMode).toBe('estimator');
    expect(JSON.parse(JSON.stringify(layout))).toEqual(layout);
  });
});
