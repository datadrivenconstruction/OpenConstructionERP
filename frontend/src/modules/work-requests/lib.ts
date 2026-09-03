// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Pure helpers for the Work Requests screens - dates, hours arithmetic,
 * colours, sorting and the two error shapes the contract names. No React,
 * nothing fetched, so every rule here is unit-testable on its own.
 */

import { ApiError } from '@/shared/lib/api';
import { fmtCurrency, fmtDate, getIntlLocale, fmtFixed, fmtList } from '@/shared/lib/formatters';
import type {
  ChecklistItem,
  Department,
  Person,
  Priority,
  RequestField,
  RequestType,
  Stage,
  Status,
  UserRow,
  WorkRequest,
} from './api';

/* ── Errors the contract names ───────────────────────────────────── */

/** True when the server simply does not carry this module (404/405). */
export function isModuleMissing(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 405);
}

/**
 * The caller may read this but may not write it - `work_requests.manage`
 * is manager-level. The Manage screen asks for it rather than assuming,
 * so a 403 turns the editors read-only with one honest line instead of
 * throwing a toast per keystroke.
 */
export function isForbidden(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 401 || err.status === 403);
}

/** A 404 on ONE endpoint of a module that is otherwise present - the
 *  request-type editor before the backend that serves it has landed. */
export function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

export interface Conflict {
  error: string;
  allowed: string[];
}

/** The 409 body `{detail: {error, allowed: []}}`, or null for anything else. */
export function conflictOf(err: unknown): Conflict | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === 'object' ? body.detail : null;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const d = detail as { error?: unknown; allowed?: unknown };
    return {
      error: typeof d.error === 'string' && d.error ? d.error : err.message,
      allowed: Array.isArray(d.allowed) ? d.allowed.map(String) : [],
    };
  }
  return { error: err.message, allowed: [] };
}

/** One line for a toast or an inline banner. */
export function errorText(err: unknown): string {
  const c = conflictOf(err);
  if (c) return c.allowed.length ? `${c.error} (allowed: ${fmtList(c.allowed)})` : c.error;
  if (err instanceof Error) return err.message;
  return String(err);
}

/* ── Dates ───────────────────────────────────────────────────────── */

const pad2 = (n: number) => String(n).padStart(2, '0');

/** Local calendar day as YYYY-MM-DD. */
export function isoDay(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

/** YYYY-MM-DD -> local Date at midnight (no timezone shift). */
export function dayOf(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
}

export function addDays(iso: string, n: number): string {
  const d = dayOf(iso);
  d.setDate(d.getDate() + n);
  return isoDay(d);
}

/** The Monday of the week holding `iso`. */
export function mondayOf(iso: string): string {
  const d = dayOf(iso);
  const dow = (d.getDay() + 6) % 7; // Mon=0 … Sun=6
  d.setDate(d.getDate() - dow);
  return isoDay(d);
}

export function isWeekend(iso: string): boolean {
  const dow = dayOf(iso).getDay();
  return dow === 0 || dow === 6;
}

/** Every day from `from` to `to` inclusive. */
export function daysBetween(from: string, to: string): string[] {
  const out: string[] = [];
  let cur = from;
  let guard = 0;
  while (cur <= to && guard < 400) {
    out.push(cur);
    cur = addDays(cur, 1);
    guard += 1;
  }
  return out;
}

/** Weekdays only, grouped by the Monday that starts their week. */
export function weeksOf(days: string[]): { monday: string; days: string[] }[] {
  const groups = new Map<string, string[]>();
  for (const d of days) {
    if (isWeekend(d)) continue;
    const mon = mondayOf(d);
    const list = groups.get(mon) ?? [];
    list.push(d);
    groups.set(mon, list);
  }
  return Array.from(groups.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([monday, ds]) => ({ monday, days: ds }));
}

/** The first day of the month holding `iso`. */
export function firstOfMonth(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

/**
 * `n` months on. Clamped to the target month's own length, so "one month
 * after 31 Jan" is 28 Feb rather than the 3rd of March that a naive
 * `setMonth` produces - a month grid that skips February entirely.
 */
export function addMonths(iso: string, n: number): string {
  const d = dayOf(firstOfMonth(iso));
  const day = dayOf(iso).getDate();
  d.setMonth(d.getMonth() + n);
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
  d.setDate(Math.min(day, last));
  return isoDay(d);
}

/** 'YYYY-MM-DD' -> "September 2026", in the reader's own locale. */
export function monthLabel(iso: string): string {
  return dayOf(iso).toLocaleDateString(getIntlLocale(), { month: 'long', year: 'numeric' });
}

export function sameMonth(a: string, b: string): boolean {
  return a.slice(0, 7) === b.slice(0, 7);
}

/**
 * The month grid: whole Monday-first weeks covering the month holding
 * `iso`, six rows only when the month actually needs one - a February
 * that starts on a Monday is five rows, and padding it to six draws a
 * whole empty week of March.
 */
export function monthGrid(iso: string): string[][] {
  const first = firstOfMonth(iso);
  const start = mondayOf(first);
  const lastDay = new Date(dayOf(first).getFullYear(), dayOf(first).getMonth() + 1, 0);
  const end = isoDay(lastDay);
  const weeks: string[][] = [];
  let cur = start;
  // At most six rows: 31 days over a week starting on a Sunday is 6×7.
  for (let w = 0; w < 6; w += 1) {
    const row = Array.from({ length: 7 }, (_, i) => addDays(cur, i));
    weeks.push(row);
    cur = addDays(cur, 7);
    if (cur > end) break;
  }
  return weeks;
}

/** The seven Monday-first weekday names, short, in the reader's locale. */
export function weekdayHeads(): string[] {
  // 2024-01-01 was a Monday - any known Monday will do.
  return Array.from({ length: 7 }, (_, i) => dayOf(addDays('2024-01-01', i)).toLocaleDateString(getIntlLocale(), { weekday: 'short' }));
}

/**
 * A calendar day, in the format the rest of the ERP uses.
 *
 * Every other screen reads dates through `fmtDate`, which honours the
 * user's Settings → Regional date-format preference (dd/mm vs mm/dd) and
 * pins a date-only string to UTC so the calendar day never slips. Rolling
 * our own `toLocaleDateString` here printed "Tue 2 Sep" beside the app's
 * "02 Sep 2026" on the same screen, and ignored the preference entirely.
 */
export function fmtDay(iso: string | null | undefined): string {
  if (!iso) return '—';
  if (Number.isNaN(dayOf(iso).getTime())) return iso;
  return fmtDate(iso.slice(0, 10));
}

/** 'YYYY-MM-DD' -> "2 Sep" (planner column heads - no year, it is a grid). */
export function fmtDayShort(iso: string): string {
  const d = dayOf(iso);
  return d.toLocaleDateString(getIntlLocale(), { day: 'numeric', month: 'short' });
}

/** 'YYYY-MM-DD' -> "Oct". */
export function monthShort(iso: string): string {
  return dayOf(iso).toLocaleDateString(getIntlLocale(), { month: 'short' });
}

/**
 * The label for one planner column. The heads were day-of-month alone, so
 * a five-week window that crossed a month read "… 29 30 02 03 …" - two
 * days that look adjacent and a month that vanished. The first column and
 * every column that starts a new month say which month it is; the rest
 * stay bare, because a grid of "01 Oct 02 Oct 03 Oct" is unreadable noise.
 */
export function dayHead(iso: string, prev: string | undefined): { day: string; month: string | null } {
  const day = iso.slice(8);
  const turns = !prev || prev.slice(0, 7) !== iso.slice(0, 7);
  return { day, month: turns ? monthShort(iso) : null };
}

/** Any ISO instant -> "02 Sep 2026, 14:05", in the app's date format. */
export function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return fmtDate(iso, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/* ── Money ───────────────────────────────────────────────────────── */

/**
 * The backend carries money as Decimal-as-TEXT (`"5220.00"`), not as a
 * number - `cost_at_completion` and a department's `hourly_rate` both
 * arrive as strings. `Number(…)` them before any arithmetic, and render
 * through the ERP's own `fmtCurrency` so a cost reads "5,220" like every
 * other money on the screen rather than the raw "5220.00".
 */
export function moneyNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Money for display: grouped, no stray decimals. `—` when there is none. */
export function fmtMoney(value: string | number | null | undefined): string {
  const n = moneyNumber(value);
  return n === null ? '—' : fmtCurrency(n);
}

/** "in 3 days" / "today" / "4 days overdue" from the server's day count. */
export function dueWords(req: Pick<WorkRequest, 'due_date' | 'days_until_due' | 'is_overdue'>): string {
  if (!req.due_date) return '';
  const n = req.days_until_due;
  if (n === null || n === undefined) return fmtDay(req.due_date);
  if (n === 0) return 'due today';
  if (n < 0) return `${-n} day${n === -1 ? '' : 's'} overdue`;
  return `in ${n} day${n === 1 ? '' : 's'}`;
}

/**
 * The same distance as a CLAUSE that can be joined to a sentence.
 *
 * `dueWords` gives the bare fragment a table cell wants ("in 57 days"),
 * which read as gibberish the moment the banner glued it to the ball
 * pill: "With Workshop. in 57 days". This one says what the number is a
 * distance TO, so "With Workshop · due in 57 days" is a sentence.
 *
 * Null when there is no due date at all - the caller then says nothing
 * rather than printing an empty separator.
 */
export function dueClause(
  req: Pick<WorkRequest, 'due_date' | 'days_until_due' | 'is_overdue'>,
): { text: string; overdue: boolean } | null {
  if (!req.due_date) return null;
  const n = req.days_until_due;
  if (n === null || n === undefined) return { text: `due ${fmtDay(req.due_date)}`, overdue: !!req.is_overdue };
  if (n === 0) return { text: 'due today', overdue: !!req.is_overdue };
  if (n < 0) return { text: `overdue by ${-n} day${n === -1 ? '' : 's'}`, overdue: true };
  return { text: `due in ${n} day${n === 1 ? '' : 's'}`, overdue: false };
}

/* ── Lateness (the department's own promise) ─────────────────────── */

/**
 * "Late" is NOT "overdue". Overdue is the requester's due date; late is
 * the DEPARTMENT's promise - its `target_days` from acceptance, which the
 * server turns into `target_date` and then `is_late` / `days_late`.
 *
 * The server's own flag wins. When it sends a `target_date` but no flag
 * (an older serialiser, a payload assembled by hand) the day is compared
 * here so a target that has plainly passed still reads as late. With
 * neither, nothing is claimed: a pill invented from the due date would be
 * a second overdue badge wearing a different word.
 */
export function isLate(req: Pick<WorkRequest, 'is_late' | 'target_date' | 'status'>, today?: string): boolean {
  if (isClosed(req.status)) return false;
  if (typeof req.is_late === 'boolean') return req.is_late;
  if (!req.target_date) return false;
  return req.target_date.slice(0, 10) < (today ?? isoDay(new Date()));
}

/** How many days past the target, or null when the server did not say. */
export function daysLate(req: Pick<WorkRequest, 'is_late' | 'days_late' | 'target_date' | 'status'>, today?: string): number | null {
  if (!isLate(req)) return null;
  if (typeof req.days_late === 'number') return req.days_late;
  if (!req.target_date) return null;
  const now = dayOf(today ?? isoDay(new Date())).getTime();
  const target = dayOf(req.target_date).getTime();
  const days = Math.round((now - target) / 86_400_000);
  return days > 0 ? days : null;
}

/** "late" / "3 days late" - the pill's own words. */
export function lateWords(req: Pick<WorkRequest, 'is_late' | 'days_late' | 'target_date' | 'status'>): string {
  const n = daysLate(req);
  if (n === null) return 'late';
  return `${n} day${n === 1 ? '' : 's'} late`;
}

/* ── Checklists ──────────────────────────────────────────────────── */

/**
 * A request's checklist. Absent is not empty on the wire - a server with
 * no checklists sends nothing at all - but it IS the same to a screen:
 * both mean "no list to draw", and neither may throw.
 */
export function checklistOf(req: Pick<WorkRequest, 'checklist'>): ChecklistItem[] {
  return Array.isArray(req.checklist) ? req.checklist : [];
}

/**
 * "4 of 7". The server's own counts win when it sends them (it may count
 * items this payload trimmed); otherwise the list is counted here.
 */
export function checklistProgress(req: Pick<WorkRequest, 'checklist' | 'checklist_done' | 'checklist_total'>): { done: number; total: number } {
  const items = checklistOf(req);
  const total = typeof req.checklist_total === 'number' ? req.checklist_total : items.length;
  const done = typeof req.checklist_done === 'number' ? req.checklist_done : items.filter((i) => i.done).length;
  return { done, total };
}

/** The required items still outstanding - what a closing stage waits on. */
export function outstandingRequired(req: Pick<WorkRequest, 'checklist'>): ChecklistItem[] {
  return checklistOf(req).filter((i) => i.required && !i.done);
}

/**
 * Whether the reader is on the DEPARTMENT's side of this request - the
 * only side that may tick its checklist. The requester raised it and
 * reads it; the workshop does the work and signs it off.
 *
 * Membership is the department's own list, plus whoever the request is
 * assigned to (a request handed to somebody outside the listed members is
 * still theirs to tick). A department that lists NOBODY treats everyone
 * as a member - the same rule `memberPool` uses for its pickers, and the
 * honest reading of an unconfigured department: an empty list is a
 * department nobody has set up, not a department nobody belongs to.
 *
 * The server is still the authority. This only decides whether to offer a
 * tick that would be refused; a signed-out reader (`me` null) is offered
 * nothing, because there is nobody to record as having ticked it.
 */
export function onDepartmentSide(
  req: Pick<WorkRequest, 'assignees' | 'responsible' | 'department'>,
  dept: Department | undefined,
  me: Me | null,
): boolean {
  if (!me) return false;
  if (req.assignees.some((a) => a.id === me.id) || req.responsible?.id === me.id) return true;
  const members = dept?.member_ids ?? [];
  if (members.length === 0) return true;
  return members.includes(me.id) || dept?.lead_user_id === me.id;
}

/**
 * Whether to OFFER checklist editing - adding, renaming, reordering and
 * removing the lines themselves, which is a different right from ticking
 * them. The server grants it to `work_requests.manage` or to the
 * department's own lead, and stays the authority: this only decides
 * whether to show controls that would 403. A 403 is surfaced with the
 * server's own sentence, which names who can.
 */
export function canEditChecklist(dept: Department | undefined, me: Me | null, canManage: boolean): boolean {
  if (!me) return false;
  return canManage || dept?.lead_user_id === me.id;
}

/* ── Hours ───────────────────────────────────────────────────────── */

export const HOURS_PER_HEAD_DAY = 8;

export function fmtHours(h: number | null | undefined): string {
  if (h === null || h === undefined || Number.isNaN(h)) return '—';
  return Number.isInteger(h) ? `${h}h` : `${fmtFixed(h, 1)}h`;
}

/** Signed deviation: "+4h" (over the quote, bad), "−2h" (under, good). */
export function fmtDeviation(h: number | null | undefined): string {
  if (h === null || h === undefined || Number.isNaN(h)) return '—';
  if (h === 0) return '0h';
  const abs = Number.isInteger(h) ? String(Math.abs(h)) : fmtFixed(Math.abs(h), 1);
  return `${h > 0 ? '+' : '−'}${abs}h`;
}

/** At-completion when the server did not compute it: logged + to-complete. */
export function atCompletion(req: Pick<WorkRequest, 'hours_at_completion' | 'hours_logged' | 'hours_to_complete'>): number | null {
  if (req.hours_at_completion !== null && req.hours_at_completion !== undefined) return req.hours_at_completion;
  if (req.hours_to_complete === null || req.hours_to_complete === undefined) return null;
  return (req.hours_logged ?? 0) + req.hours_to_complete;
}

/** Logged and forecast as a share of the quote, for a CSS bar. */
export function hoursBar(req: Pick<WorkRequest, 'quoted_hours' | 'hours_logged' | 'hours_at_completion' | 'hours_to_complete'>): {
  logged: number;
  forecast: number;
  over: boolean;
  quoted: number | null;
} {
  const quoted = req.quoted_hours ?? null;
  const logged = req.hours_logged ?? 0;
  const ac = atCompletion(req) ?? logged;
  const denom = Math.max(quoted ?? 0, ac, logged, 1);
  return {
    logged: Math.min(100, (logged / denom) * 100),
    forecast: Math.min(100, (ac / denom) * 100),
    over: quoted !== null && ac > quoted,
    quoted,
  };
}

export function sum(values: Iterable<number | null | undefined>): number {
  let t = 0;
  for (const v of values) t += v ?? 0;
  return t;
}

/* ── Colours / people ────────────────────────────────────────────── */

const PALETTE = ['#6136ad', '#2f42a8', '#1361c9', '#06657f', '#0a6f66', '#14713d', '#4f6a10', '#8a5406', '#a4470c', '#a52f5b', '#a92c23', '#55616e'];

export const NEUTRAL = '#55616e';

/**
 * A department's, a stage's and a request type's colour arrives from the
 * server as a TOKEN - `"blue"`, `"rose"`, `"red"` - not as CSS. Three of
 * the tokens the backend accepts (`slate`, `amber`, `rose`) are not CSS
 * colour keywords at all, so `color-mix(in srgb, rose 66%, …)` was
 * invalid and the whole declaration was dropped: on the live seed the
 * Hazardous Area tab dot and every `WR-HAZ-…` chip measured
 * `rgba(0, 0, 0, 0)` - no colour at all. The tokens that ARE keywords
 * resolved to the raw ones (`blue` is #0000ff, `violet` is #ee82ee),
 * nothing like the mid-dark inks the rest of the module is drawn in.
 *
 * So a token is resolved to this palette's own hex before it reaches any
 * CSS, and anything already CSS (a hex someone picked in Manage) passes
 * straight through. `red` maps to #a92c23 rather than #f00 for the same
 * reason every other entry is mid-dark: `tintStyle` mixes it 66% towards
 * near-black in the light theme and 56% towards white in the dark one,
 * and that is what holds both over the 4.5:1 AA floor.
 */
export const COLOUR_TOKENS: Record<string, string> = {
  slate: NEUTRAL,
  grey: NEUTRAL,
  gray: NEUTRAL,
  blue: '#1361c9',
  indigo: '#2f42a8',
  violet: '#6136ad',
  purple: '#6136ad',
  cyan: '#06657f',
  teal: '#0a6f66',
  green: '#14713d',
  lime: '#4f6a10',
  amber: '#8a5406',
  yellow: '#8a5406',
  orange: '#a4470c',
  rose: '#a52f5b',
  pink: '#a52f5b',
  red: '#a92c23',
};

/** The palette a colour picker offers, token → hex, in spectrum order. */
export const COLOUR_CHOICES: { token: string; hex: string }[] = [
  'blue',
  'indigo',
  'violet',
  'cyan',
  'teal',
  'green',
  'lime',
  'amber',
  'orange',
  'rose',
  'red',
  'slate',
].map((token) => ({ token, hex: COLOUR_TOKENS[token] ?? NEUTRAL }));

/** A server colour token as real CSS. Unknown text is passed through. */
export function resolveColour(colour: string | null | undefined): string {
  if (!colour) return NEUTRAL;
  const key = colour.trim().toLowerCase();
  return COLOUR_TOKENS[key] ?? colour;
}

/** A stable colour for a string (same name -> same colour everywhere). */
export function tintFor(key: string): string {
  let h = 0;
  for (let i = 0; i < key.length; i += 1) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length] ?? NEUTRAL;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] ?? '' : '';
  return (first + last).toUpperCase() || first.toUpperCase();
}

/**
 * A soft wash + coloured text from any CSS colour, readable in BOTH themes.
 *
 * The palette is a set of mid-dark inks chosen against white. Painted
 * straight onto the dark theme's near-black panel they measured 2.8:1
 * ("with Workshop", #55616e) and 2.9:1 ("In progress", #0a6f66) - under
 * the 4.5:1 AA floor. So the ink is mixed towards `--wr-tint-ink`, which
 * wr.css sets to near-black in the light theme (a shade deeper, still
 * clearly the department's colour) and to white in the dark one.
 */
export function tintStyle(colour: string): { color: string; background: string; borderColor: string } {
  const c = resolveColour(colour);
  return {
    color: `color-mix(in srgb, ${c} var(--wr-tint-mix, 85%), var(--wr-tint-ink, #0b1220))`,
    background: `color-mix(in srgb, ${c} var(--wr-tint-wash, 14%), transparent)`,
    borderColor: `color-mix(in srgb, ${c} var(--wr-tint-edge, 35%), transparent)`,
  };
}

export const STATUS_LABEL: Record<Status, string> = {
  draft: 'Draft',
  submitted: 'Submitted',
  accepted: 'Accepted',
  in_progress: 'In progress',
  on_hold: 'On hold',
  review: 'In review',
  complete: 'Complete',
  closed: 'Closed',
  cancelled: 'Cancelled',
};

export const STATUS_COLOUR: Record<Status, string> = {
  draft: '#77818d',
  submitted: '#2f42a8',
  accepted: '#1361c9',
  in_progress: '#0a6f66',
  on_hold: '#8a5406',
  review: '#6136ad',
  complete: '#14713d',
  closed: '#55616e',
  cancelled: '#a92c23',
};

export const PRIORITY_GLYPH: Record<Priority, string> = {
  low: '↓',
  normal: '',
  high: '!',
  urgent: '‼',
};

export const PRIORITY_LABEL: Record<Priority, string> = {
  low: 'Low',
  normal: 'Normal',
  high: 'High',
  urgent: 'Urgent',
};

export function isClosed(status: Status): boolean {
  return status === 'complete' || status === 'closed' || status === 'cancelled';
}

/* ── The status machine ──────────────────────────────────────────── */

/**
 * What each status may move to, mirroring the server's own table. The
 * server is still the authority - a request's payload carries its live
 * `allowed_transitions` and every write is checked there - but the board
 * needs to know the SHAPE of the graph before it asks.
 */
export const STATUS_TRANSITIONS: Record<Status, Status[]> = {
  draft: ['submitted', 'cancelled'],
  submitted: ['accepted', 'cancelled'],
  accepted: ['in_progress', 'on_hold', 'cancelled'],
  in_progress: ['on_hold', 'review', 'complete', 'cancelled'],
  on_hold: ['accepted', 'in_progress', 'review', 'cancelled'],
  review: ['in_progress', 'complete', 'cancelled'],
  complete: ['closed', 'in_progress'],
  closed: [],
  cancelled: [],
};

/**
 * The hops that get a request from `from` to `to`, or `null` when the
 * machine has no route at all.
 *
 * Dropping a card from Submitted onto In progress is one gesture, but
 * `submitted → in_progress` is not a legal edge: the department has to
 * ACCEPT the request first. The board used to PATCH the target status
 * straight in and show the server's 409 - which is correct about the
 * rules and useless about the intent. This returns `['accepted',
 * 'in_progress']` so the drop can walk the two steps the server wants.
 *
 * `allowed` (the request's live `allowed_transitions`) constrains the
 * first hop when the server has narrowed it further than the static
 * table - a permission or a rule the client cannot see.
 */
export function statusPath(from: Status, to: Status, allowed?: string[]): Status[] | null {
  if (from === to) return [];
  const first = allowed && allowed.length ? (allowed as Status[]) : STATUS_TRANSITIONS[from] ?? [];
  if (first.includes(to)) return [to];
  for (const hop of first) {
    if ((STATUS_TRANSITIONS[hop] ?? []).includes(to)) return [hop, to];
  }
  return null;
}

/* ── Departments / stages ────────────────────────────────────────── */

export function stagesOf(dept: Department | undefined): Stage[] {
  return [...(dept?.stages ?? [])].sort((a, b) => a.order - b.order);
}

export function stageOf(dept: Department | undefined, key: string): Stage | undefined {
  return dept?.stages.find((s) => s.key === key);
}

export function deptOf(departments: Department[] | undefined, key: string): Department | undefined {
  return departments?.find((d) => d.key === key);
}

/* ── Request types (a request may carry several) ─────────────────── */

/**
 * A department's request types in the server's own order, active only
 * unless asked. `active` and `position` are new on the contract, so a
 * type that carries neither is treated as active and keeps the order the
 * server listed it in - the UI must not blank a department's types just
 * because it is talking to a backend that has not shipped the fields.
 */
export function typesOf(dept: Department | undefined, includeInactive = false): RequestType[] {
  const list = (dept?.request_types ?? []).map((t, i) => ({ t, i }));
  list.sort((a, b) => (a.t.position ?? a.i) - (b.t.position ?? b.i) || a.i - b.i);
  const ordered = list.map(({ t }) => t);
  return includeInactive ? ordered : ordered.filter((t) => t.active !== false);
}

export function typeOf(dept: Department | undefined, key: string): RequestType | undefined {
  return dept?.request_types.find((t) => t.key === key);
}

/**
 * Every type key on a request. `request_types` is the new contract and
 * `request_type` is the first of them kept for anything that predates
 * it, so a payload carrying only the legacy field IS a one-type request
 * rather than a typeless one.
 */
export function typeKeysOf(req: Pick<WorkRequest, 'request_type' | 'request_types'>): string[] {
  const many = req.request_types;
  if (Array.isArray(many) && many.length > 0) return many.filter(Boolean);
  return req.request_type ? [req.request_type] : [];
}

/**
 * The labels to print for a request's types. The server's own
 * `request_type_labels` win (it knows a type the department has since
 * retired); otherwise the department's list is consulted and the raw key
 * is the last resort, so a retired type still reads as something.
 */
export function typeLabelsOf(
  req: Pick<WorkRequest, 'request_type' | 'request_types' | 'request_type_labels'>,
  dept: Department | undefined,
): string[] {
  const keys = typeKeysOf(req);
  const given = req.request_type_labels;
  if (Array.isArray(given) && given.length === keys.length && given.every(Boolean)) return given;
  return keys.map((k) => typeOf(dept, k)?.label ?? k);
}

/**
 * The de-duplicated UNION of several types' fields, first occurrence
 * winning and the chosen order kept - the same rule the server applies
 * to build `field_specs`, computed here so the raise dialog asks the
 * right questions before the backend that computes it has landed.
 */
export function unionFields(types: RequestType[]): RequestField[] {
  const seen = new Set<string>();
  const out: RequestField[] = [];
  for (const t of types) {
    for (const f of t.fields ?? []) {
      if (seen.has(f.key)) continue;
      seen.add(f.key);
      out.push(f);
    }
  }
  return out;
}

/** The same union for the disciplines the hours / cost-centre grid asks. */
export function unionDisciplines(types: RequestType[]): string[] {
  const seen = new Set<string>();
  for (const t of types) for (const d of t.disciplines ?? []) seen.add(d);
  return Array.from(seen);
}

/**
 * The fields a request's form is made of: the server's `field_specs`
 * when it sends them (it validates against exactly those), else the
 * union worked out from the department's own types.
 */
export function fieldSpecsOf(
  req: Pick<WorkRequest, 'request_type' | 'request_types' | 'field_specs'>,
  dept: Department | undefined,
): RequestField[] {
  const given = req.field_specs;
  if (Array.isArray(given) && given.length > 0) return given;
  const types = typeKeysOf(req)
    .map((k) => typeOf(dept, k))
    .filter((t): t is RequestType => !!t);
  return unionFields(types);
}

/**
 * A user id turned into a person's name, or NULL when this screen cannot
 * say who it is.
 *
 * The wire carries ids in places a reader expects a person - a checklist
 * tick's `by` is a uuid, and printing it produced rows reading
 * "e58c94e2-3258-… · Sep 03, 2026" under every signed-off item. Null is
 * the honest answer for an id the loaded users do not cover (a user
 * removed since, a list still in flight); the caller shows nothing rather
 * than a uuid, because a uuid tells nobody anything.
 *
 * Also accepts a name that is already a name: the older payloads put one
 * in `by`, and a value that matches no id but is plainly not an id is
 * passed through rather than blanked.
 */
export function nameOfUser(users: UserRow[] | undefined, id: string | null | undefined): string | null {
  const raw = (id ?? '').trim();
  if (!raw) return null;
  const hit = (users ?? []).find((u) => u.id === raw);
  if (hit) return hit.full_name || hit.email || null;
  return looksLikeId(raw) ? null : raw;
}

/** A uuid, or any other opaque handle no reader should be shown. */
export function looksLikeId(value: string): boolean {
  const v = value.trim();
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v)) return true;
  // A bare hex or base-ish blob with no spaces is an id too - names have
  // spaces or letters that are not hex.
  return v.length >= 16 && !/\s/.test(v) && /^[0-9a-fA-F-]+$/.test(v);
}

/**
 * A URL a person can read. The IFC-drawing field printed
 * "http://127.0.0.1:5200/projects/cdf558ff-5ad6-…/files" across a whole
 * row - all of it noise except the two words at each end - so what is
 * shown is the host and the last meaningful segment. The FULL url still
 * rides along in `title` and in `href`; nothing is hidden, only shortened.
 */
export function shortUrl(raw: string, max = 44): string {
  const value = (raw ?? '').trim();
  if (!value) return '';
  try {
    const u = new URL(value);
    const parts = u.pathname.split('/').filter(Boolean);
    const last = decodeURIComponent(parts[parts.length - 1] ?? '');
    const tail = last && !looksLikeId(last) ? last : parts.length > 1 ? decodeURIComponent(parts[0] ?? '') : '';
    const shown = tail ? `${u.host}/${parts.length > 1 ? '…/' : ''}${tail}` : u.host;
    return shown.length > max ? `${shown.slice(0, max - 1)}…` : shown;
  } catch {
    return value.length > max ? `${value.slice(0, max - 1)}…` : value;
  }
}

/** The people a department offers first; everyone when it lists nobody. */
export function memberPool(dept: Department | undefined, users: UserRow[]): UserRow[] {
  const ids = new Set(dept?.member_ids ?? []);
  if (ids.size === 0) return users;
  const members = users.filter((u) => ids.has(u.id));
  return members.length ? members : users;
}

/* ── Who holds the ball ──────────────────────────────────────────── */

export interface Me {
  id: string;
  name: string;
}

/** "with you" when the ball is on the reader's side of the net. */
export function ballWords(
  req: Pick<WorkRequest, 'ball_in_court' | 'raised_by_id' | 'raised_by_name' | 'assignees' | 'responsible' | 'department'>,
  me: Me | null,
  deptName: string,
): { withYou: boolean; label: string } {
  const mine =
    !!me &&
    (req.ball_in_court === 'requester'
      ? req.raised_by_id === me.id
      : req.assignees.some((a) => a.id === me.id) || req.responsible?.id === me.id);
  if (mine) return { withYou: true, label: 'with you' };
  if (req.ball_in_court === 'requester') return { withYou: false, label: `with ${req.raised_by_name || 'requester'}` };
  return { withYou: false, label: `with ${deptName || req.department}` };
}

export function personNames(people: Person[]): string {
  return fmtList(people.map((p) => p.name));
}

/* ── Sorting ─────────────────────────────────────────────────────── */

export type SortKey =
  | 'reference'
  | 'title'
  | 'project'
  | 'client'
  | 'type'
  | 'stage'
  | 'status'
  | 'responsible'
  | 'assignees'
  | 'due'
  | 'hours'
  | 'ball';

function sortValue(r: WorkRequest, key: SortKey): string | number {
  switch (key) {
    case 'reference':
      return r.reference;
    case 'title':
      return r.title.toLowerCase();
    case 'project':
      return `${r.project_code ?? ''} ${r.project_name ?? ''}`.toLowerCase();
    case 'client':
      return (r.client_name ?? '').toLowerCase();
    case 'type':
      return r.request_type;
    case 'stage':
      return r.stage ?? '';
    case 'status':
      return STATUSES.indexOf(r.status);
    case 'responsible':
      return (r.responsible?.name ?? '').toLowerCase();
    case 'assignees':
      return personNames(r.assignees).toLowerCase();
    case 'due':
      return r.due_date ?? '9999-99-99';
    case 'hours':
      return r.deviation_hours ?? -Infinity;
    case 'ball':
      return r.ball_in_court;
  }
}

const STATUSES: Status[] = ['draft', 'submitted', 'accepted', 'in_progress', 'on_hold', 'review', 'complete', 'closed', 'cancelled'];

export function sortRequests(rows: WorkRequest[], key: SortKey, dir: 'asc' | 'desc'): WorkRequest[] {
  const sign = dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = sortValue(a, key);
    const vb = sortValue(b, key);
    if (va < vb) return -1 * sign;
    if (va > vb) return 1 * sign;
    return a.reference.localeCompare(b.reference);
  });
}

/**
 * The type filter is ANY-OF, matching `GET /requests?request_types=a,b`:
 * a request that carries SCADA, PLC and FDS answers a filter for any one
 * of them. Applied client-side on top of the server's own filter so the
 * list is right even against a backend that ignores the parameter.
 */
export function matchesTypes(req: Pick<WorkRequest, 'request_type' | 'request_types'>, keys: string[]): boolean {
  if (keys.length === 0) return true;
  const mine = new Set(typeKeysOf(req));
  return keys.some((k) => mine.has(k));
}

/** Client-side text filter used on top of the server's `q`. */
export function matchesText(r: WorkRequest, needle: string): boolean {
  const n = needle.trim().toLowerCase();
  if (!n) return true;
  return [r.reference, r.title, r.project_code, r.project_name, r.client_name, r.raised_by_name, r.responsible?.name ?? '', personNames(r.assignees)]
    .join(' ')
    .toLowerCase()
    .includes(n);
}

/* ── What the month view plots ───────────────────────────────────── */

/**
 * Which of a request's dates the month grid draws. A work request is not
 * a calendar event with one date on it: the due date is the promise, the
 * info-required-by is what the department is waiting on, and each type
 * brings its own dates ("Tested by", "Date the factory receives
 * drawings") that live in `fields` and are described by `field_specs`.
 * The grid plots one of the three at a time and says which.
 */
export type DateMode = 'due' | 'info' | 'key';

export const DATE_MODES: DateMode[] = ['due', 'info', 'key'];

export interface Plot {
  req: WorkRequest;
  /** The ISO day it sits on. */
  day: string;
  /**
   * The field key behind it: `due_date`, `info_required_by`, or a typed
   * field's own key. Drops are only legal on `due_date` - the others are
   * the server's or the type's, not something a drag may rewrite.
   */
  key: string;
  /** What to CALL that date on the chip, in "Key dates" mode. */
  label: string;
}

/** A `fields` value that is a date, normalised to YYYY-MM-DD, else null. */
function dateValue(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const s = raw.trim().slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : null;
}

/** The typed date fields a request carries, with their labels and values. */
export function keyDatesOf(req: WorkRequest, dept: Department | undefined): { key: string; label: string; day: string }[] {
  const out: { key: string; label: string; day: string }[] = [];
  for (const f of fieldSpecsOf(req, dept)) {
    if (f.type !== 'date') continue;
    const day = dateValue(req.fields?.[f.key]);
    if (day) out.push({ key: f.key, label: f.label || f.key, day });
  }
  return out;
}

/**
 * Every chip the grid draws, for one mode. A request appears once in Due
 * and Info-required-by modes and once PER typed date in Key dates - a
 * switchboard with a factory date and a test date is two chips, which is
 * the whole point of the mode.
 */
export function plotsFor(rows: WorkRequest[], mode: DateMode, departments: Department[] | undefined): Plot[] {
  const out: Plot[] = [];
  for (const req of rows) {
    if (mode === 'due') {
      if (req.due_date) out.push({ req, day: req.due_date.slice(0, 10), key: 'due_date', label: 'Due' });
    } else if (mode === 'info') {
      if (req.info_required_by) out.push({ req, day: req.info_required_by.slice(0, 10), key: 'info_required_by', label: 'Info required by' });
    } else {
      for (const d of keyDatesOf(req, deptOf(departments, req.department))) out.push({ req, day: d.day, key: d.key, label: d.label });
    }
  }
  // Overdue and open first, then by reference, so a day of four reads the
  // same every render and the "+N more" always hides the same tail.
  return out.sort((a, b) => {
    const la = a.key === 'due_date' && a.req.is_overdue && !isClosed(a.req.status) ? 0 : 1;
    const lb = b.key === 'due_date' && b.req.is_overdue && !isClosed(b.req.status) ? 0 : 1;
    return la - lb || a.req.reference.localeCompare(b.req.reference) || a.key.localeCompare(b.key);
  });
}

/** The plots of one mode, bucketed by ISO day. */
export function plotsByDay(plots: Plot[]): Map<string, Plot[]> {
  const map = new Map<string, Plot[]>();
  for (const p of plots) {
    const list = map.get(p.day);
    if (list) list.push(p);
    else map.set(p.day, [p]);
  }
  return map;
}

/* ── Planner arithmetic ──────────────────────────────────────────── */

/** Headcount × 8 over every day of a row, in hours. */
export function rowHours(alloc: Record<string, number>): number {
  return sum(Object.values(alloc)) * HOURS_PER_HEAD_DAY;
}

/** Sum of a column across every row. */
export function columnHeads(rows: { alloc: Record<string, number> }[], day: string): number {
  return sum(rows.map((r) => r.alloc[day]));
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
