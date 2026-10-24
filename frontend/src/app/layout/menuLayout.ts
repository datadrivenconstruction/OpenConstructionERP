// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The user's menu arrangement as one serialisable object: item order inside
 * groups, group order, user groups, work modes and the collapsed-sidebar
 * style. A company template can later be laid underneath with
 * `resolveMenuLayout(template, overrides)`; the user's own changes stay on
 * top and "Reset to default" drops them.
 */

export type MenuModeId = 'estimator' | 'site_manager' | 'finance' | 'manager' | 'all';
export type RailState = 'open' | 'icons' | 'rail';

export const MENU_MODE_IDS: readonly MenuModeId[] = ['estimator', 'site_manager', 'finance', 'manager', 'all'];

export interface UserMenuGroup {
  id: string;
  label: string;
  items: string[];
}

export interface MenuLayout {
  version: 1;
  /** Route order per group id; routes not listed keep catalogue order after them. */
  order: Record<string, string[]>;
  /** Group ids in display order; unlisted groups follow in catalogue order. */
  groupOrder: string[];
  userGroups: UserMenuGroup[];
  /** Routes per mode; 'all' is never stored (it shows every row). */
  modes: Partial<Record<MenuModeId, string[]>>;
  activeMode: MenuModeId;
  rail: RailState;
}

/** Sensible defaults for construction work in any market: 8-12 rows each. */
export const DEFAULT_MODE_ITEMS: Record<Exclude<MenuModeId, 'all'>, string[]> = {
  estimator: [
    '/', '/projects', '/takeoff?tab=measurements', '/dwg-takeoff', '/quantities', '/boq',
    '/costs', '/assemblies', '/cost-match', '/tendering', '/rfq-bidding', '/validation',
  ],
  site_manager: [
    '/', '/projects', '/daily-diary', '/schedule', '/tasks', '/rfi',
    '/issues', '/inspections', '/punchlist', '/safety', '/photos', '/site-logistics',
  ],
  finance: [
    '/', '/projects', '/finance', '/cost-control', '/contracts', '/changeorders',
    '/payment-clock', '/cvr', '/procurement', '/subcontractors', '/reports',
  ],
  manager: [
    '/', '/projects', '/portfolio', '/schedule', '/cost-control', '/risks',
    '/changeorders', '/meetings', '/dashboards', '/reports', '/tasks',
  ],
};

export const DEFAULT_MENU_LAYOUT: MenuLayout = {
  version: 1,
  order: {},
  groupOrder: [],
  userGroups: [],
  modes: {},
  activeMode: 'all',
  rail: 'open',
};

export type MenuLayoutAction =
  | { type: 'moveItem'; groupId: string; current: string[]; from: number; to: number }
  | { type: 'moveGroup'; current: string[]; from: number; to: number }
  | { type: 'addUserGroup'; id: string; label: string }
  | { type: 'renameUserGroup'; id: string; label: string }
  | { type: 'removeUserGroup'; id: string }
  | { type: 'toggleUserGroupItem'; id: string; route: string }
  | { type: 'setMode'; mode: MenuModeId }
  | { type: 'toggleModeItem'; mode: Exclude<MenuModeId, 'all'>; route: string }
  | { type: 'resetMode'; mode: Exclude<MenuModeId, 'all'> }
  | { type: 'setRail'; rail: RailState }
  | { type: 'reset' };

/** Move one entry, clamped to the list; returns the same array when nothing moves. */
export function moveInList<T>(list: readonly T[], from: number, to: number): T[] {
  if (from < 0 || from >= list.length) return [...list];
  const target = Math.max(0, Math.min(list.length - 1, to));
  if (target === from) return [...list];
  const next = [...list];
  const [moved] = next.splice(from, 1);
  next.splice(target, 0, moved as T);
  return next;
}

/** Sort `items` by a stored key order; unknown keys keep their original order after the known ones. */
export function applyOrder<T>(items: readonly T[], order: readonly string[] | undefined, key: (item: T) => string): T[] {
  if (!order || order.length === 0) return [...items];
  const rank = new Map(order.map((k, i) => [k, i]));
  return items
    .map((item, i) => ({ item, i, r: rank.get(key(item)) }))
    .sort((a, b) => {
      if (a.r != null && b.r != null) return a.r - b.r;
      if (a.r != null) return -1;
      if (b.r != null) return 1;
      return a.i - b.i;
    })
    .map((x) => x.item);
}

export function modeItems(layout: MenuLayout, mode: MenuModeId): string[] | null {
  if (mode === 'all') return null;
  return layout.modes[mode] ?? DEFAULT_MODE_ITEMS[mode];
}

export function menuLayoutReducer(state: MenuLayout, action: MenuLayoutAction): MenuLayout {
  switch (action.type) {
    case 'moveItem': {
      const next = moveInList(action.current, action.from, action.to);
      if (action.groupId.startsWith('user:')) {
        const id = action.groupId.slice(5);
        return {
          ...state,
          userGroups: state.userGroups.map((g) => (g.id === id ? { ...g, items: next } : g)),
        };
      }
      if (action.groupId.startsWith('mode:')) {
        const mode = action.groupId.slice(5) as Exclude<MenuModeId, 'all'>;
        return { ...state, modes: { ...state.modes, [mode]: next } };
      }
      return { ...state, order: { ...state.order, [action.groupId]: next } };
    }
    case 'moveGroup':
      return { ...state, groupOrder: moveInList(action.current, action.from, action.to) };
    case 'addUserGroup': {
      const label = action.label.trim();
      if (!label || state.userGroups.some((g) => g.id === action.id)) return state;
      return { ...state, userGroups: [...state.userGroups, { id: action.id, label, items: [] }] };
    }
    case 'renameUserGroup': {
      const label = action.label.trim();
      if (!label) return state;
      return { ...state, userGroups: state.userGroups.map((g) => (g.id === action.id ? { ...g, label } : g)) };
    }
    case 'removeUserGroup':
      return { ...state, userGroups: state.userGroups.filter((g) => g.id !== action.id) };
    case 'toggleUserGroupItem':
      return {
        ...state,
        userGroups: state.userGroups.map((g) =>
          g.id !== action.id
            ? g
            : {
                ...g,
                items: g.items.includes(action.route)
                  ? g.items.filter((r) => r !== action.route)
                  : [...g.items, action.route],
              },
        ),
      };
    case 'setMode':
      return MENU_MODE_IDS.includes(action.mode) ? { ...state, activeMode: action.mode } : state;
    case 'toggleModeItem': {
      const current = modeItems(state, action.mode) ?? [];
      const next = current.includes(action.route)
        ? current.filter((r) => r !== action.route)
        : [...current, action.route];
      return { ...state, modes: { ...state.modes, [action.mode]: next } };
    }
    case 'resetMode': {
      const modes = { ...state.modes };
      delete modes[action.mode];
      return { ...state, modes };
    }
    case 'setRail':
      return { ...state, rail: action.rail };
    case 'reset':
      // Keep the chosen mode and sidebar style; reset is about the arrangement.
      return { ...DEFAULT_MENU_LAYOUT, activeMode: state.activeMode, rail: state.rail };
    default:
      return state;
  }
}

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === 'string');
}

/** Parse untrusted JSON (storage or a company template) into a valid partial layout. */
export function sanitizeMenuLayout(raw: unknown): Partial<MenuLayout> {
  if (!raw || typeof raw !== 'object') return {};
  const r = raw as Record<string, unknown>;
  const out: Partial<MenuLayout> = {};
  if (r.order && typeof r.order === 'object') {
    const order: Record<string, string[]> = {};
    for (const [k, v] of Object.entries(r.order as Record<string, unknown>)) if (isStringArray(v)) order[k] = v;
    out.order = order;
  }
  if (isStringArray(r.groupOrder)) out.groupOrder = r.groupOrder;
  if (Array.isArray(r.userGroups)) {
    out.userGroups = r.userGroups.filter(
      (g): g is UserMenuGroup =>
        !!g && typeof g.id === 'string' && typeof g.label === 'string' && isStringArray(g.items),
    );
  }
  if (r.modes && typeof r.modes === 'object') {
    const modes: Partial<Record<MenuModeId, string[]>> = {};
    for (const [k, v] of Object.entries(r.modes as Record<string, unknown>)) {
      if (k !== 'all' && MENU_MODE_IDS.includes(k as MenuModeId) && isStringArray(v)) modes[k as MenuModeId] = v;
    }
    out.modes = modes;
  }
  if (typeof r.activeMode === 'string' && MENU_MODE_IDS.includes(r.activeMode as MenuModeId)) {
    out.activeMode = r.activeMode as MenuModeId;
  }
  if (r.rail === 'open' || r.rail === 'icons' || r.rail === 'rail') out.rail = r.rail;
  return out;
}

/** Defaults, then a company template, then the user's overrides on top. */
export function resolveMenuLayout(template: unknown, overrides: unknown): MenuLayout {
  const t = sanitizeMenuLayout(template);
  const u = sanitizeMenuLayout(overrides);
  return {
    ...DEFAULT_MENU_LAYOUT,
    ...t,
    ...u,
    order: { ...(t.order ?? {}), ...(u.order ?? {}) },
    modes: { ...(t.modes ?? {}), ...(u.modes ?? {}) },
    version: 1,
  };
}
