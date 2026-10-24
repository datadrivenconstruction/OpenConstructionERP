// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Theme resolution: light, dark, follow the system, or dark by time of day.
 *
 * Pure so the store, the settings preview and the boot script in index.html
 * agree; `__tests__/appearanceBoot.test.ts` runs that script against these keys.
 */

export const THEME_MODES = ['light', 'dark', 'system', 'schedule'] as const;
export type ThemeMode = (typeof THEME_MODES)[number];
export type ResolvedTheme = 'light' | 'dark';

/** Dark from `darkFrom` o'clock until `darkTo` o'clock, local time, whole hours. */
export interface ThemeSchedule {
  darkFrom: number;
  darkTo: number;
}

export const THEME_KEY = 'oe_theme';
export const THEME_SCHEDULE_KEY = 'oe_theme_schedule';
export const DEFAULT_SCHEDULE: ThemeSchedule = { darkFrom: 19, darkTo: 7 };

export function isThemeMode(v: unknown): v is ThemeMode {
  return typeof v === 'string' && (THEME_MODES as readonly string[]).includes(v);
}

function isHour(v: unknown): v is number {
  return typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= 23;
}

export function sanitizeSchedule(raw: unknown): ThemeSchedule | null {
  if (!raw || typeof raw !== 'object') return null;
  const { darkFrom, darkTo } = raw as Record<string, unknown>;
  return isHour(darkFrom) && isHour(darkTo) ? { darkFrom, darkTo } : null;
}

/** Whether `hour` falls in the dark window; the window may wrap past midnight. */
export function isDarkHour(hour: number, s: ThemeSchedule): boolean {
  if (s.darkFrom === s.darkTo) return false;
  return s.darkFrom < s.darkTo ? hour >= s.darkFrom && hour < s.darkTo : hour >= s.darkFrom || hour < s.darkTo;
}

export function resolveTheme(
  mode: ThemeMode,
  env: { systemDark: boolean; hour: number; schedule: ThemeSchedule },
): ResolvedTheme {
  if (mode === 'system') return env.systemDark ? 'dark' : 'light';
  if (mode === 'schedule') return isDarkHour(env.hour, env.schedule) ? 'dark' : 'light';
  return mode;
}

export function readStoredSchedule(): ThemeSchedule {
  try {
    return sanitizeSchedule(JSON.parse(localStorage.getItem(THEME_SCHEDULE_KEY) || 'null')) ?? DEFAULT_SCHEDULE;
  } catch {
    return DEFAULT_SCHEDULE;
  }
}

export function readStoredThemeMode(): ThemeMode {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return isThemeMode(v) ? v : 'system';
  } catch {
    return 'system';
  }
}
