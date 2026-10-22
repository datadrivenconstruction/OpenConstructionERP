// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Personal work preferences kept on this device: the page opened after sign-in
 * and the first day of the week. `weekStart: 'auto'` follows the UI locale.
 */
export const LANDING_PAGES = ['dashboard', 'projects', 'boq', 'tasks', 'schedule', 'inbox'] as const;
export const WEEK_STARTS = ['auto', 'monday', 'sunday', 'saturday'] as const;

export type LandingPage = (typeof LANDING_PAGES)[number];
export type WeekStart = (typeof WEEK_STARTS)[number];

export interface WorkPrefs {
  landing: LandingPage;
  weekStart: WeekStart;
}

export const DEFAULT_WORK_PREFS: WorkPrefs = { landing: 'dashboard', weekStart: 'auto' };
export const WORK_PREFS_KEY = 'oe_work_prefs_v1';

const listeners = new Set<() => void>();

export function subscribeWorkPrefs(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function readWorkPrefs(): WorkPrefs {
  try {
    const raw = JSON.parse(localStorage.getItem(WORK_PREFS_KEY) ?? 'null') as Partial<Record<keyof WorkPrefs, unknown>> | null;
    return {
      landing: LANDING_PAGES.includes(raw?.landing as LandingPage)
        ? (raw!.landing as LandingPage)
        : DEFAULT_WORK_PREFS.landing,
      weekStart: WEEK_STARTS.includes(raw?.weekStart as WeekStart)
        ? (raw!.weekStart as WeekStart)
        : DEFAULT_WORK_PREFS.weekStart,
    };
  } catch {
    return { ...DEFAULT_WORK_PREFS };
  }
}

export function writeWorkPrefs(next: WorkPrefs): void {
  try {
    localStorage.setItem(WORK_PREFS_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: applies until reload */
  }
  listeners.forEach((cb) => cb());
}

/** Route opened after sign-in (what `/` redirects to). */
export function landingPath(): string {
  return `/${readWorkPrefs().landing}`;
}

/** The chosen first day as date-fns `weekStartsOn`, or null to follow the locale. */
export function weekStartOverride(): 0 | 1 | 6 | null {
  const w = readWorkPrefs().weekStart;
  return w === 'monday' ? 1 : w === 'sunday' ? 0 : w === 'saturday' ? 6 : null;
}
