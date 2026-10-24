// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * UI appearance styles: accent colour, font, density, corner radius, text size
 * and contrast.
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
export const TEXT_SIZES = ['standard', 'large', 'xlarge'] as const;
export const CONTRASTS = ['standard', 'high'] as const;

export type Accent = (typeof ACCENTS)[number];
export type FontChoice = (typeof FONTS)[number];
export type Density = (typeof DENSITIES)[number];
export type Radius = (typeof RADII)[number];
export type TextSize = (typeof TEXT_SIZES)[number];
export type Contrast = (typeof CONTRASTS)[number];

export interface Appearance {
  accent: Accent;
  font: FontChoice;
  density: Density;
  radius: Radius;
  text: TextSize;
  contrast: Contrast;
}

export type AppearanceAxis = keyof Appearance;

export const AXIS_VALUES: { [K in AppearanceAxis]: readonly Appearance[K][] } = {
  accent: ACCENTS,
  font: FONTS,
  density: DENSITIES,
  radius: RADII,
  text: TEXT_SIZES,
  contrast: CONTRASTS,
};

export const PLATFORM_APPEARANCE: Appearance = {
  accent: 'blue',
  font: 'system',
  density: 'comfortable',
  radius: 'standard',
  text: 'standard',
  contrast: 'standard',
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

/**
 * Named styles, one click each. A preset only sets existing axes and the theme,
 * so anything it does can also be reached by hand below the gallery.
 */
export interface AppearancePreset {
  id: 'classic' | 'office' | 'site' | 'night' | 'presentation';
  value: Appearance;
  theme: 'light' | 'dark';
}

const base = PLATFORM_APPEARANCE;
export const APPEARANCE_PRESETS: readonly AppearancePreset[] = [
  { id: 'classic', value: base, theme: 'light' },
  {
    id: 'office',
    value: { ...base, accent: 'graphite', font: 'inter', density: 'compact', radius: 'sharp' },
    theme: 'light',
  },
  // Tablet in sunlight: big letters, strong contrast, generous touch targets.
  {
    id: 'site',
    value: { ...base, accent: 'amber', density: 'comfortable', radius: 'round', text: 'xlarge', contrast: 'high' },
    theme: 'light',
  },
  { id: 'night', value: { ...base, accent: 'teal', font: 'inter' }, theme: 'dark' },
  // A client looking at a big screen from across the table.
  {
    id: 'presentation',
    value: { ...base, accent: 'blue', font: 'inter', radius: 'round', text: 'large' },
    theme: 'light',
  },
];

const AXES = Object.keys(PLATFORM_APPEARANCE) as AppearanceAxis[];

/**
 * The preset an appearance matches exactly, or null for a custom mix. With a
 * theme mode given the preset's theme must match too; `system` and `schedule`
 * never match, since no preset picks them.
 */
export function matchPreset(a: Appearance, theme?: string): AppearancePreset['id'] | null {
  const hit = APPEARANCE_PRESETS.find(
    (p) => AXES.every((k) => p.value[k] === a[k]) && (theme === undefined || p.theme === theme),
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
  root.dataset.text = a.text;
  root.dataset.contrast = a.contrast;
  ensureFontLoaded(a.font);
}
