// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Personal work preferences kept on this device: the page opened after sign-in,
 * the page opened with a project (per the project's setup role) and the first
 * day of the week. `weekStart: 'auto'` follows the UI locale.
 */
export const LANDING_PAGES = ['dashboard', 'projects', 'boq', 'tasks', 'schedule', 'inbox'] as const;
export const WEEK_STARTS = ['auto', 'monday', 'sunday', 'saturday'] as const;

/** Roles of the project setup profile (`ROLE_AFFINITY` in the projects backend). */
export const PROJECT_ROLES = [
  'client_owner',
  'general_contractor',
  'subcontractor',
  'cost_engineer',
  'designer_architect',
  'bim_manager',
  'bim_consultant',
  'developer',
] as const;
/** Pages a project can open on; `overview` is the project page itself (today's behaviour). */
export const PROJECT_START_PAGES = ['overview', 'boq', 'tasks', 'schedule', 'inbox'] as const;

export type LandingPage = (typeof LANDING_PAGES)[number];
export type ProjectRole = (typeof PROJECT_ROLES)[number];
export type ProjectStartPage = (typeof PROJECT_START_PAGES)[number];
export type WeekStart = (typeof WEEK_STARTS)[number];

export interface WorkPrefs {
  landing: LandingPage;
  weekStart: WeekStart;
  /** Only roles that differ from `overview` are stored. */
  projectStart: Partial<Record<ProjectRole, ProjectStartPage>>;
}

export const DEFAULT_WORK_PREFS: WorkPrefs = { landing: 'dashboard', weekStart: 'auto', projectStart: {} };
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
    const projectStart: WorkPrefs['projectStart'] = {};
    const stored = raw?.projectStart;
    if (stored && typeof stored === 'object') {
      for (const role of PROJECT_ROLES) {
        const page = (stored as Record<string, unknown>)[role];
        if (PROJECT_START_PAGES.includes(page as ProjectStartPage) && page !== 'overview') {
          projectStart[role] = page as ProjectStartPage;
        }
      }
    }
    return {
      landing: LANDING_PAGES.includes(raw?.landing as LandingPage)
        ? (raw!.landing as LandingPage)
        : DEFAULT_WORK_PREFS.landing,
      weekStart: WEEK_STARTS.includes(raw?.weekStart as WeekStart)
        ? (raw!.weekStart as WeekStart)
        : DEFAULT_WORK_PREFS.weekStart,
      projectStart,
    };
  } catch {
    return { ...DEFAULT_WORK_PREFS, projectStart: {} };
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

/** True when at least one role opens a project somewhere other than its page. */
export function hasProjectStart(prefs: WorkPrefs = readWorkPrefs()): boolean {
  return Object.keys(prefs.projectStart).length > 0;
}

/** Page chosen for a project setup role, `overview` when none is set. */
export function projectStartFor(role: string | null | undefined): ProjectStartPage {
  return (role ? readWorkPrefs().projectStart[role as ProjectRole] : undefined) ?? 'overview';
}
