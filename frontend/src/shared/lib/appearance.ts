// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * UI appearance styles: accent colour, font, density and corner radius.
 *
 * Each axis is a `data-*` attribute on <html> that index.css turns into token
 * overrides. The boot script in index.html applies the same attributes from
 * localStorage before first paint, so this module and that script must agree on
 * the storage keys, the allowed values and the font stylesheet paths; the test
 * in `__tests__/appearanceBoot.test.ts` runs the real script to hold them together.
 *
 * Resolution order per axis: the user's own choice, then the workspace default
 * an admin set (cached from GET /api/v1/branding/), then the platform default.
 */

export const ACCENTS = ['blue', 'teal', 'violet', 'emerald', 'amber', 'graphite', 'crimson'] as const;
export const FONTS = ['system', 'inter', 'ibm-plex-sans', 'source-sans-3'] as const;
export const DENSITIES = ['comfortable', 'compact'] as const;
export const RADII = ['standard', 'sharp', 'round'] as const;

export type Accent = (typeof ACCENTS)[number];
export type FontChoice = (typeof FONTS)[number];
export type Density = (typeof DENSITIES)[number];
export type Radius = (typeof RADII)[number];

export interface Appearance {
  accent: Accent;
  font: FontChoice;
  density: Density;
  radius: Radius;
}

export type AppearanceAxis = keyof Appearance;

export const AXIS_VALUES: { [K in AppearanceAxis]: readonly Appearance[K][] } = {
  accent: ACCENTS,
  font: FONTS,
  density: DENSITIES,
  radius: RADII,
};

export const PLATFORM_APPEARANCE: Appearance = {
  accent: 'blue',
  font: 'system',
  density: 'comfortable',
  radius: 'standard',
};

/** The user's own choice. Read by the boot script in index.html. */
export const USER_APPEARANCE_KEY = 'oe_appearance_v1';
/** Cached workspace default, so it applies before the server answers. */
export const WORKSPACE_APPEARANCE_KEY = 'oe_workspace_appearance_v1';

/** Swatch colours for previews: the light-mode accent base from index.css. */
export const ACCENT_SWATCH: Record<Accent, string> = {
  blue: '#0071e3',
  teal: '#0f766e',
  violet: '#7c3aed',
  emerald: '#047857',
  amber: '#a84d08',
  graphite: '#475569',
  crimson: '#be123c',
};

/** Display names of the web fonts. Proper names, not translated. */
export const FONT_FAMILY_NAME: Record<Exclude<FontChoice, 'system'>, string> = {
  inter: 'Inter',
  'ibm-plex-sans': 'IBM Plex Sans',
  'source-sans-3': 'Source Sans 3',
};

/** CSS font-family for previews; index.css carries the same stacks. */
export const FONT_STACK: Record<FontChoice, string> = {
  system: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif',
  inter: '"Inter Variable", -apple-system, BlinkMacSystemFont, Arial, sans-serif',
  'ibm-plex-sans': '"IBM Plex Sans Variable", -apple-system, BlinkMacSystemFont, Arial, sans-serif',
  'source-sans-3': '"Source Sans 3 Variable", -apple-system, BlinkMacSystemFont, Arial, sans-serif',
};

export interface AppearancePreset {
  id: 'classic' | 'studio' | 'engineering' | 'warm' | 'executive';
  value: Appearance;
}

export const APPEARANCE_PRESETS: readonly AppearancePreset[] = [
  { id: 'classic', value: PLATFORM_APPEARANCE },
  { id: 'studio', value: { accent: 'violet', font: 'inter', density: 'comfortable', radius: 'round' } },
  { id: 'engineering', value: { accent: 'teal', font: 'ibm-plex-sans', density: 'compact', radius: 'sharp' } },
  { id: 'warm', value: { accent: 'amber', font: 'source-sans-3', density: 'comfortable', radius: 'round' } },
  { id: 'executive', value: { accent: 'graphite', font: 'inter', density: 'comfortable', radius: 'standard' } },
];

/** The preset an appearance matches exactly, or null for a custom mix. */
export function matchPreset(a: Appearance): AppearancePreset['id'] | null {
  const hit = APPEARANCE_PRESETS.find((p) =>
    (Object.keys(PLATFORM_APPEARANCE) as AppearanceAxis[]).every((k) => p.value[k] === a[k]),
  );
  return hit ? hit.id : null;
}

/** Keep only known axes with allowed values; null when nothing is left. */
export function sanitizeAppearance(raw: unknown): Partial<Appearance> | null {
  if (!raw || typeof raw !== 'object') return null;
  const src = raw as Record<string, unknown>;
  const out: Partial<Appearance> = {};
  for (const axis of Object.keys(AXIS_VALUES) as AppearanceAxis[]) {
    const v = src[axis];
    if (typeof v === 'string' && (AXIS_VALUES[axis] as readonly string[]).includes(v)) {
      (out as Record<string, string>)[axis] = v;
    }
  }
  return Object.keys(out).length ? out : null;
}

export function resolveAppearance(
  user: Partial<Appearance> | null,
  workspace: Partial<Appearance> | null,
): Appearance {
  return { ...PLATFORM_APPEARANCE, ...(workspace ?? {}), ...(user ?? {}) };
}

export function readStoredAppearance(key: string): Partial<Appearance> | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? sanitizeAppearance(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

export function writeStoredAppearance(key: string, value: Partial<Appearance> | null): void {
  try {
    if (value) localStorage.setItem(key, JSON.stringify(value));
    else localStorage.removeItem(key);
  } catch {
    /* storage unavailable: the choice still applies for this session */
  }
}

/** Public URL of a web font's stylesheet; null for the system stack. */
export function fontStylesheetHref(font: FontChoice): string | null {
  return font === 'system' ? null : `/assets/vendor/fonts/${font}.css`;
}

/**
 * Link a web font's stylesheet once. Only the chosen font (or one shown in a
 * preview) is ever fetched, and unicode-range keeps unused subsets off the wire.
 */
export function ensureFontLoaded(font: FontChoice): void {
  const href = fontStylesheetHref(font);
  if (!href || typeof document === 'undefined') return;
  if (document.head.querySelector(`link[data-oe-font="${font}"]`)) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = href;
  link.dataset.oeFont = font;
  document.head.appendChild(link);
}

/** Put an appearance on <html>. Mirrors the boot script in index.html. */
export function applyAppearance(a: Appearance, root: HTMLElement = document.documentElement): void {
  root.dataset.accent = a.accent;
  root.dataset.font = a.font;
  root.dataset.density = a.density;
  root.dataset.radius = a.radius;
  ensureFontLoaded(a.font);
}
