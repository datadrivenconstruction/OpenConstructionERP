// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Menu look: how the sidebar is laid out and how its icons are drawn.
 *
 * Same mechanism as the style axes in `appearance.ts`: each axis becomes a
 * `data-menu-<axis>` attribute on <html>, index.css turns it into sidebar rules,
 * and the boot script in index.html paints it from localStorage before first
 * paint. Resolution per axis: the user's choice, then the workspace default
 * (branding `appearance.menu`), then the platform default.
 *
 * Per-item icon overrides map a menu route to the name of an icon from the
 * curated catalogue in `app/layout/menuIconCatalog.ts`. They are personal and
 * never part of the workspace default.
 */

export const MENU_VIEWS = ['classic', 'compact', 'comfortable', 'rail', 'floating'] as const;
export const MENU_ACTIVES = ['bar', 'pill', 'tint'] as const;
export const MENU_HEADERS = ['caps', 'divider', 'none'] as const;
export const MENU_STROKES = ['light', 'regular', 'bold'] as const;
export const MENU_CONTAINERS = ['none', 'tile', 'circle'] as const;
export const MENU_COLORS = ['mono', 'accent', 'sections'] as const;
export const MENU_ICONS = ['shown', 'hidden'] as const;

export interface MenuLook {
  view: (typeof MENU_VIEWS)[number];
  active: (typeof MENU_ACTIVES)[number];
  headers: (typeof MENU_HEADERS)[number];
  stroke: (typeof MENU_STROKES)[number];
  container: (typeof MENU_CONTAINERS)[number];
  color: (typeof MENU_COLORS)[number];
  icons: (typeof MENU_ICONS)[number];
}

export type MenuAxis = keyof MenuLook;

export const MENU_AXIS_VALUES: { [K in MenuAxis]: readonly MenuLook[K][] } = {
  view: MENU_VIEWS,
  active: MENU_ACTIVES,
  headers: MENU_HEADERS,
  stroke: MENU_STROKES,
  container: MENU_CONTAINERS,
  color: MENU_COLORS,
  icons: MENU_ICONS,
};

export const MENU_AXES = Object.keys(MENU_AXIS_VALUES) as MenuAxis[];

/** The menu as it always looked. */
export const PLATFORM_MENU: MenuLook = {
  view: 'classic',
  active: 'bar',
  headers: 'caps',
  stroke: 'regular',
  container: 'none',
  color: 'mono',
  icons: 'shown',
};

/** Lucide stroke width per weight; index.css carries the same numbers. */
export const MENU_STROKE_WIDTH: Record<MenuLook['stroke'], number> = { light: 1.25, regular: 1.75, bold: 2.25 };

export const MENU_PRESET_IDS = ['classic', 'studio', 'blueprint', 'site_office', 'executive', 'focus'] as const;
export type MenuPresetId = (typeof MENU_PRESET_IDS)[number];

export interface MenuPreset {
  id: MenuPresetId;
  value: MenuLook;
}

export const MENU_PRESETS: readonly MenuPreset[] = [
  { id: 'classic', value: PLATFORM_MENU },
  {
    id: 'studio',
    value: { view: 'comfortable', active: 'pill', headers: 'divider', stroke: 'light', container: 'tile', color: 'accent', icons: 'shown' },
  },
  {
    id: 'blueprint',
    value: { view: 'compact', active: 'bar', headers: 'divider', stroke: 'light', container: 'none', color: 'accent', icons: 'shown' },
  },
  {
    id: 'site_office',
    value: { view: 'comfortable', active: 'pill', headers: 'caps', stroke: 'bold', container: 'tile', color: 'sections', icons: 'shown' },
  },
  {
    id: 'executive',
    value: { view: 'floating', active: 'tint', headers: 'none', stroke: 'regular', container: 'circle', color: 'mono', icons: 'shown' },
  },
  {
    id: 'focus',
    value: { view: 'compact', active: 'tint', headers: 'caps', stroke: 'regular', container: 'none', color: 'mono', icons: 'hidden' },
  },
];

/** The preset a menu look matches exactly, or null for a custom mix. */
export function matchMenuPreset(m: MenuLook): MenuPresetId | null {
  const hit = MENU_PRESETS.find((p) => MENU_AXES.every((k) => p.value[k] === m[k]));
  return hit ? hit.id : null;
}

/** Keep only known axes with allowed values; null when nothing is left. */
export function sanitizeMenu(raw: unknown): Partial<MenuLook> | null {
  if (!raw || typeof raw !== 'object') return null;
  const src = raw as Record<string, unknown>;
  const out: Partial<MenuLook> = {};
  for (const axis of MENU_AXES) {
    const v = src[axis];
    if (typeof v === 'string' && (MENU_AXIS_VALUES[axis] as readonly string[]).includes(v)) {
      (out as Record<string, string>)[axis] = v;
    }
  }
  return Object.keys(out).length ? out : null;
}

export function resolveMenu(user: Partial<MenuLook> | null, workspace: Partial<MenuLook> | null): MenuLook {
  return { ...PLATFORM_MENU, ...(workspace ?? {}), ...(user ?? {}) };
}

/** The user's own menu look. Read by the boot script in index.html. */
export const USER_MENU_KEY = 'oe_menu_v1';
/** Cached workspace default menu look. Read by the boot script too. */
export const WORKSPACE_MENU_KEY = 'oe_workspace_menu_v1';
/** Per-item icon overrides: `{ "<route>": "<icon name>" }`. */
export const MENU_ICON_OVERRIDES_KEY = 'oe_menu_icons_v1';

export function readStoredMenu(key: string): Partial<MenuLook> | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? sanitizeMenu(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

export function writeStoredMenu(key: string, value: Partial<MenuLook> | null): void {
  try {
    if (value) localStorage.setItem(key, JSON.stringify(value));
    else localStorage.removeItem(key);
  } catch {
    /* storage unavailable: the choice still applies for this session */
  }
}

/** Route -> icon name. A route is an app path, an icon name a PascalCase word. */
export type IconOverrides = Record<string, string>;

const ROUTE_RE = /^\/[\w\-/?=&.]{0,120}$/;
const ICON_NAME_RE = /^[A-Z][A-Za-z0-9]{1,40}$/;

export function sanitizeIconOverrides(raw: unknown): IconOverrides {
  const out: IconOverrides = {};
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return out;
  for (const [route, name] of Object.entries(raw as Record<string, unknown>)) {
    if (ROUTE_RE.test(route) && typeof name === 'string' && ICON_NAME_RE.test(name)) out[route] = name;
  }
  return out;
}

export function readIconOverrides(): IconOverrides {
  try {
    const raw = localStorage.getItem(MENU_ICON_OVERRIDES_KEY);
    return raw ? sanitizeIconOverrides(JSON.parse(raw)) : {};
  } catch {
    return {};
  }
}

export function writeIconOverrides(value: IconOverrides): void {
  try {
    if (Object.keys(value).length) localStorage.setItem(MENU_ICON_OVERRIDES_KEY, JSON.stringify(value));
    else localStorage.removeItem(MENU_ICON_OVERRIDES_KEY);
  } catch {
    /* storage unavailable */
  }
}

/** Put a menu look on <html>. Mirrors the boot script in index.html. */
export function applyMenu(m: MenuLook, root: HTMLElement = document.documentElement): void {
  for (const axis of MENU_AXES) root.setAttribute(`data-menu-${axis}`, m[axis]);
}

/**
 * Section colours for the "per-section" icon colour. index.css defines the
 * same values as `--oe-tone-<n>`; the test holds every one at WCAG AA (4.5:1)
 * on the sidebar surfaces and on the row tints in both themes.
 */
export const SECTION_TONES: readonly { light: string; dark: string }[] = [
  { light: '#1e40af', dark: '#93c5fd' }, // blue
  { light: '#115e59', dark: '#5eead4' }, // teal
  { light: '#5b21b6', dark: '#c4b5fd' }, // violet
  { light: '#92400e', dark: '#fcd34d' }, // amber
  { light: '#065f46', dark: '#6ee7b7' }, // emerald
  { light: '#9f1239', dark: '#fda4af' }, // rose
  { light: '#155e75', dark: '#67e8f9' }, // cyan
  { light: '#9a3412', dark: '#fdba74' }, // orange
];
