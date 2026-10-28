// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Where an open shift lives between page loads.
 *
 * A punch-in is never queued. It cannot be: the hours are not known until the
 * shift ends, so only the punch-out becomes a mutation. That makes the open
 * shift's only record the crew roster held by the tab, and holding it in
 * memory alone meant closing the tab lost it without a word. A worker who
 * pockets their phone at the start of a shift is the ordinary case on a site,
 * not an edge one, and the loss is silent: nothing is queued, so the sync
 * badge shows nothing pending and everything looks fine.
 *
 * Keyed by project rather than by day, so a shift running past midnight is
 * still open when the phone comes back.
 */

export interface CrewMember {
  id: string;
  name: string;
  task: string;
  /** ISO time when the punch-in started, or null when not punched in. */
  startedAt: string | null;
  /**
   * The register id of the person these hours belong to, empty when the name
   * was typed.
   *
   * The desktop timesheet reconciles on exactly this, so a punch without one
   * cannot be matched and the same person is counted once from the phone and
   * once from the office. Empty is still allowed: a subcontractor's worker who
   * is in nobody's register has to be recordable, and hours nobody can match
   * beat hours nobody took.
   */
  resourceId: string;
}

const CREW_STORAGE_PREFIX = 'oe_field_crew_v1:';

export function crewStorageKey(projectId: string): string {
  return `${CREW_STORAGE_PREFIX}${projectId}`;
}

function isCrewMember(value: unknown): value is Omit<CrewMember, 'resourceId'> &
  Partial<Pick<CrewMember, 'resourceId'>> {
  if (!value || typeof value !== 'object') return false;
  const row = value as Partial<CrewMember>;
  return (
    typeof row.id === 'string' &&
    typeof row.name === 'string' &&
    typeof row.task === 'string' &&
    (row.startedAt === null || typeof row.startedAt === 'string') &&
    // Written by a build that predates the picker. Such a row is a real open
    // shift and dropping it would end somebody's day for them, so the field is
    // optional on the way in and normalised on the way out.
    (row.resourceId === undefined || typeof row.resourceId === 'string')
  );
}

/**
 * The roster as it was left, or an empty one.
 *
 * Rows that do not read as a crew member are dropped individually rather than
 * failing the whole read: a roster written by an older build should cost the
 * worker the rows that changed shape, not the shift they are standing in.
 */
export function readStoredCrew(projectId: string): CrewMember[] {
  if (!projectId) return [];
  try {
    const raw = window.localStorage.getItem(crewStorageKey(projectId));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isCrewMember).map((row) => ({ ...row, resourceId: row.resourceId ?? '' }));
  } catch {
    return [];
  }
}

export function writeStoredCrew(projectId: string, crew: CrewMember[]): void {
  if (!projectId) return;
  try {
    window.localStorage.setItem(crewStorageKey(projectId), JSON.stringify(crew));
  } catch {
    /* Private mode, or the quota is full. The shift stays in memory, which is
       where it used to live anyway, so this is no worse than before. */
  }
}

export function clearStoredCrew(projectId: string): void {
  if (!projectId) return;
  try {
    window.localStorage.removeItem(crewStorageKey(projectId));
  } catch {
    /* nothing to do */
  }
}

/**
 * The calendar day a shift belongs to, which is the day it began.
 *
 * Not the day it ended. A night shift punched in at 22:00 and out at 02:00
 * would otherwise be filed against a day the worker had not started, and the
 * day they did work would show nobody on site. This only became reachable
 * once an open punch survived a reload, so it is a question this change had
 * to answer rather than one it inherited.
 *
 * Computed in local time, because a site works to the clock on the wall.
 */
export function shiftDate(startedAt: string, fallback: string): string {
  const started = new Date(startedAt);
  if (Number.isNaN(started.getTime())) return fallback;
  const local = new Date(started.getTime() - started.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}
