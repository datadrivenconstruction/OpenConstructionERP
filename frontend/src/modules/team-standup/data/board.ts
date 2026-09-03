// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/** Pure helpers behind the standup board - no React, no network. */

import type { Job } from '../api';

/** Every array off the wire goes through here.
 *
 * During a deploy the browser can hold the NEW chunk while the response it
 * renders came from the OLD backend (or a cached old body), so fields this
 * build takes for granted are simply absent - `job_ids`, `jobs`,
 * `open_tasks`. Reading `.length` on that undefined throws inside render and
 * drops the whole page into the error boundary. Treat a missing list as an
 * empty one: the board still draws, one degraded section instead of none.
 */
export function list<T>(value: T[] | undefined | null): T[] {
  return Array.isArray(value) ? value : [];
}

/** Local calendar day as YYYY-MM-DD.
 *
 * Never `toISOString()`: that is UTC, and for an AEST team it names
 * yesterday all morning and tomorrow late at night - the board would open
 * on the wrong day and people would post onto it.
 */
export function localDay(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** Step a YYYY-MM-DD day by whole days. Anchored at noon so a DST
 * boundary cannot land the arithmetic on the neighbouring date. */
export function shiftDay(day: string, delta: number): string {
  const d = new Date(`${day}T12:00:00`);
  d.setDate(d.getDate() + delta);
  return localDay(d);
}

/** Monday of the week containing `day` - standup weeks read Mon-Sun. */
export function weekStart(day: string): string {
  const d = new Date(`${day}T12:00:00`);
  const dow = (d.getDay() + 6) % 7; // Mon=0
  return shiftDay(day, -dow);
}

/** Job chip label: the job number leads, because that is what the team
 * calls the job out loud. */
export function jobLabel(job: Job): string {
  return job.code ? `${job.code} · ${job.name}` : job.name;
}

// ── Delivery-board filters ───────────────────────────────────────────────
// Pure predicates the engine's `visible()` calls per task. They live here
// so the rules that decide what "this week" or "unassigned" mean are
// tested on their own, not through 4,000 lines of DOM.

export type DueMode =
  | 'any'
  | 'overdue'
  | 'today'
  | 'week'
  | 'nextweek'
  | 'none'
  | 'range';

export interface DueWindow {
  /** Local YYYY-MM-DD. */
  today: string;
  /** The Friday that ends the current working week (YYYY-MM-DD). */
  endWeek: string;
  /** Range bounds, YYYY-MM-DD or '' for open-ended. */
  from?: string;
  to?: string;
}

/**
 * Does a task's due date fall inside the chosen window?
 *
 * ISO days compare as strings, so no Date arithmetic and no timezone. A
 * closed task is never "overdue" (it is finished, not late); every other
 * mode ignores the stage. "This week" runs today→Friday, "next week" is
 * the seven days after that - the same anchors the quick-date chips use,
 * so the filter and the chips agree on what a week is. A range with both
 * ends blank matches everything dated.
 */
export function dueMatches(
  due: string | null | undefined,
  done: boolean,
  mode: DueMode,
  win: DueWindow,
): boolean {
  const d = due || '';
  switch (mode) {
    case 'any':
      return true;
    case 'none':
      return !d;
    case 'overdue':
      return !!d && d < win.today && !done;
    case 'today':
      return d === win.today;
    case 'week':
      return !!d && d >= win.today && d <= win.endWeek;
    case 'nextweek':
      return !!d && d > win.endWeek && d <= shiftDay(win.endWeek, 7);
    case 'range': {
      if (!d) return false;
      if (win.from && d < win.from) return false;
      if (win.to && d > win.to) return false;
      return true;
    }
    default:
      return true;
  }
}

/** The people-filter sentinel for "no assignee on the board". */
export const UNASSIGNED = '__unassigned';

/**
 * Does a task's assignee satisfy a people filter?
 *
 * An empty selection means everyone. A task whose assignee is not on the
 * board's people list (a departed member, or no assignee at all) counts as
 * unassigned - it has nobody the team can point at.
 */
export function assigneeMatches(
  assigneeId: string,
  known: (id: string) => boolean,
  selected: readonly string[],
): boolean {
  if (!selected.length) return true;
  const key = assigneeId && known(assigneeId) ? assigneeId : UNASSIGNED;
  return selected.includes(key);
}

/**
 * Is a linked work request a switchboard job?
 *
 * The Work requests module says which department owns a request; the
 * board asks it per job and keys the answer by request id. When the
 * module has not answered for this request (closed requests are not in
 * its open-only listing, or the module is not mounted), the reference
 * itself carries the department code - `WR-WKS-…` is the workshop's.
 */
export function isWorkshopRequest(
  ref: string,
  department: string | undefined,
): boolean {
  if (department !== undefined) return department === 'workshop';
  return /^WR-WKS-/i.test(ref || '');
}
