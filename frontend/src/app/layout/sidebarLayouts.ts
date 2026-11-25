// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Named sidebar layouts: a saved arrangement of the left menu (hidden rows and
 * sections, pins, item and section order, work mode, Simple/Full) that the user
 * can store under a name and switch back to. Pure helpers only; the store
 * keeps the list on the server, per user.
 *
 * The limits mirror `backend/app/modules/users/sidebar_layouts.py`.
 */

import { sanitizeMenuLayout, type MenuLayout } from './menuLayout';

export const MAX_LAYOUTS = 20;
export const MAX_LAYOUT_NAME = 60;

export type LayoutNameError = 'empty' | 'too_long' | 'taken' | 'limit';

/** The part of the menu a layout captures. The collapsed-rail style and the
 *  panel width stay per device and are not part of it. */
export interface SidebarLayoutData {
  hiddenModules: string[];
  hiddenGroups: string[];
  pinned: string[];
  menu: Pick<MenuLayout, 'order' | 'groupOrder' | 'userGroups' | 'modes' | 'activeMode'>;
  viewMode: 'simple' | 'advanced';
}

export interface SidebarLayout {
  id: string;
  name: string;
  data: SidebarLayoutData;
}

function strings(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
}

/** Parse untrusted stored data into a complete, valid layout payload. */
export function sanitizeLayoutData(raw: unknown): SidebarLayoutData {
  const r = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const menu = sanitizeMenuLayout(r.menu);
  return {
    hiddenModules: strings(r.hiddenModules),
    hiddenGroups: strings(r.hiddenGroups),
    pinned: strings(r.pinned),
    menu: {
      order: menu.order ?? {},
      groupOrder: menu.groupOrder ?? [],
      userGroups: menu.userGroups ?? [],
      modes: menu.modes ?? {},
      activeMode: menu.activeMode ?? 'all',
    },
    viewMode: r.viewMode === 'advanced' ? 'advanced' : 'simple',
  };
}

export function normalizeLayoutName(name: string): string {
  return name.trim().replace(/\s+/g, ' ');
}

/** Why `name` cannot be used, or null when it can. `exceptId` is the layout
 *  being renamed, which may keep its own name. */
export function validateLayoutName(
  name: string,
  layouts: readonly SidebarLayout[],
  exceptId?: string,
): LayoutNameError | null {
  const clean = normalizeLayoutName(name);
  if (!clean) return 'empty';
  if (clean.length > MAX_LAYOUT_NAME) return 'too_long';
  const key = clean.toLocaleLowerCase();
  if (layouts.some((l) => l.id !== exceptId && l.name.toLocaleLowerCase() === key)) return 'taken';
  if (exceptId === undefined && layouts.length >= MAX_LAYOUTS) return 'limit';
  return null;
}

export function newLayoutId(): string {
  const c = typeof crypto !== 'undefined' ? crypto : undefined;
  if (c && 'randomUUID' in c) return c.randomUUID();
  return `l${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

export function addLayout(
  layouts: readonly SidebarLayout[],
  name: string,
  data: SidebarLayoutData,
  id: string = newLayoutId(),
): SidebarLayout[] {
  return [...layouts, { id, name: normalizeLayoutName(name), data }];
}

export function renameLayout(layouts: readonly SidebarLayout[], id: string, name: string): SidebarLayout[] {
  return layouts.map((l) => (l.id === id ? { ...l, name: normalizeLayoutName(name) } : l));
}

export function removeLayout(layouts: readonly SidebarLayout[], id: string): SidebarLayout[] {
  return layouts.filter((l) => l.id !== id);
}

export function overwriteLayout(layouts: readonly SidebarLayout[], id: string, data: SidebarLayoutData): SidebarLayout[] {
  return layouts.map((l) => (l.id === id ? { ...l, data } : l));
}

/** Parse the server list; broken entries are dropped. */
export function sanitizeLayouts(raw: unknown): SidebarLayout[] {
  if (!Array.isArray(raw)) return [];
  const out: SidebarLayout[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const r = item as Record<string, unknown>;
    if (typeof r.id !== 'string' || typeof r.name !== 'string') continue;
    out.push({ id: r.id, name: r.name, data: sanitizeLayoutData(r.data) });
  }
  return out.slice(0, MAX_LAYOUTS);
}

function same(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

/** True when the current arrangement equals the layout (order of hidden and
 *  pinned lists is not significant for hidden, it is for pins). */
export function layoutMatches(a: SidebarLayoutData, b: SidebarLayoutData): boolean {
  const sorted = (l: readonly string[]) => [...l].sort();
  return (
    same(sorted(a.hiddenModules), sorted(b.hiddenModules)) &&
    same(sorted(a.hiddenGroups), sorted(b.hiddenGroups)) &&
    same(a.pinned, b.pinned) &&
    a.viewMode === b.viewMode &&
    JSON.stringify(a.menu) === JSON.stringify(b.menu)
  );
}
