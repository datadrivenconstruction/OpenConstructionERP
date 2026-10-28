// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Unified Issue Hub - source normalizers.
//
// A "site issue" (defect, snag, clash, coordination topic, mark-up call-out)
// can be raised in at least five disjoint modules, each with its own list
// endpoint and its own item shape. This file maps every one of those shapes
// onto a single `UnifiedIssue` so the hub can show one merged, sortable list
// of what is open and who owns it.
//
// Design contract:
//   * Read only. Nothing here writes to any module.
//   * Every mapper is isolated. A missing or renamed field in one source can
//     never break another source: `useAllIssues` wraps each mapper per item
//     in a try/catch and simply drops the one bad row (see `mapEach`).
//   * Each mapper returns `null` for items that are done (terminal state) or
//     that are not really issues, so the hub only carries live, open work.

import type { Markup } from '../markups/api';
import type { PunchItem } from '../punchlist/api';
import type { NCR } from '../ncr/api';
import type { ClashIssue } from '../clash/api';
import type { NeighbourIssue } from '../site-logistics/api';

/* --- Public types --------------------------------------------------------- */

/** The issue-owning modules the hub unions. */
export type IssueSource = 'markup' | 'punch' | 'ncr' | 'bcf' | 'clash' | 'neighbour';

/** Every source status collapses into one of these four lifecycle buckets. */
export type IssueStatusBucket = 'open' | 'in_progress' | 'resolved' | 'closed';

/** Normalized urgency. `none` is used by sources that carry no priority. */
export type IssuePriority = 'critical' | 'high' | 'medium' | 'low' | 'none';

/** One row of the unified hub, produced from exactly one source item. */
export interface UnifiedIssue {
  /** Globally unique across sources, e.g. "punch:1a2b". Safe as a React key. */
  id: string;
  /** The owning module's own id for the item (used to build the deep link). */
  rawId: string;
  /** Which module this issue was raised in. */
  source: IssueSource;
  /** Best-effort human title. Never empty (falls back to a derived label). */
  title: string;
  /** Normalized lifecycle bucket. */
  status: IssueStatusBucket;
  /** The source's own status label, kept for display and tooltips. */
  rawStatus: string;
  /** Normalized urgency. */
  priority: IssuePriority;
  /** Owner token (user id or name) as the source stores it, or null. */
  assignee: string | null;
  /** ISO date/timestamp the item is due, or null when the source has none. */
  dueDate: string | null;
  /** ISO timestamp the item was created, or null. */
  createdAt: string | null;
  /** Route back to the owning module + item (react-router path + query). */
  deepLink: string;
}

/* --- Small, defensive value helpers --------------------------------------- */

function str(v: unknown): string {
  if (typeof v === 'string') return v;
  if (v == null) return '';
  return String(v);
}

function strOrNull(v: unknown): string | null {
  const s = str(v).trim();
  return s.length > 0 ? s : null;
}

function titleCaseType(type: string): string {
  if (!type) return 'Markup';
  return type.charAt(0).toUpperCase() + type.slice(1);
}

/**
 * Map any source priority/severity token onto the normalized scale. Covers
 * the punch/clash scale (low..critical) and common BCF labels (major, normal,
 * minor). Unknown or missing tokens degrade to `none`, never throw.
 */
export function normalizePriority(v: unknown): IssuePriority {
  const s = str(v).trim().toLowerCase();
  if (s === 'critical' || s === 'blocker') return 'critical';
  if (s === 'high' || s === 'major') return 'high';
  if (s === 'medium' || s === 'normal') return 'medium';
  if (s === 'low' || s === 'minor') return 'low';
  return 'none';
}

/** Sort weight for priority. Higher is more urgent. */
export const PRIORITY_RANK: Record<IssuePriority, number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
  none: 0,
};

/* --- Overdue -------------------------------------------------------------- */

/** Calendar-day number (UTC) for a Date, so date-only strings compare cleanly. */
function dayNumber(d: Date): number {
  return Math.floor(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) / 86_400_000);
}

/** The local calendar day of `now`, expressed on the same UTC-day scale. */
function todayDayNumber(now: Date): number {
  return Math.floor(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) / 86_400_000);
}

/**
 * True when the issue has a due date strictly before today. A missing or
 * unparseable due date is never overdue (safe default). "Due today" is not
 * overdue. Terminal issues never reach the hub, so no status guard is needed.
 */
export function isOverdue(issue: UnifiedIssue, now: Date = new Date()): boolean {
  if (!issue.dueDate) return false;
  const due = new Date(issue.dueDate);
  if (Number.isNaN(due.getTime())) return false;
  return dayNumber(due) < todayDayNumber(now);
}

/* --- Deep links ----------------------------------------------------------- */

function markupDeepLink(m: Markup): string {
  if (m.document_id) {
    const params = new URLSearchParams({ openDoc: m.document_id });
    if (m.page != null) params.set('page', String(m.page));
    return `/markups?${params.toString()}`;
  }
  return '/markups';
}

/* --- Status buckets per source -------------------------------------------- */

// Only non-terminal statuses appear here; anything absent is treated as done
// and dropped from the hub (mapper returns null).

const PUNCH_BUCKET: Record<string, IssueStatusBucket | undefined> = {
  open: 'open',
  in_progress: 'in_progress',
  resolved: 'resolved',
  // verified, closed -> terminal
};

const NCR_BUCKET: Record<string, IssueStatusBucket | undefined> = {
  identified: 'open',
  under_review: 'in_progress',
  corrective_action: 'in_progress',
  verification: 'resolved',
  // closed, void -> terminal
};

const NCR_PRIORITY: Record<string, IssuePriority> = {
  critical: 'critical',
  major: 'high',
  minor: 'medium',
  observation: 'low',
};

const CLASH_BUCKET: Record<string, IssueStatusBucket | undefined> = {
  new: 'open',
  persisted: 'open',
  // resolved, ignored, archived -> terminal / not-open
};

const NEIGHBOUR_BUCKET: Record<string, IssueStatusBucket | undefined> = {
  received: 'open',
  acknowledged: 'in_progress',
  action_taken: 'resolved',
  // closed -> terminal
};

/** Lower-cased BCF topic statuses that mean the topic is done. */
const BCF_CLOSED_STATUSES = new Set(['closed', 'done', 'completed']);

function bcfBucket(rawStatus: string): IssueStatusBucket | undefined {
  const s = rawStatus.trim().toLowerCase();
  if (BCF_CLOSED_STATUSES.has(s)) return undefined;
  if (s === 'resolved' || s === 'fixed') return 'resolved';
  if (s === 'assigned' || s === 'in progress' || s === 'in_progress' || s === 'inprogress') {
    return 'in_progress';
  }
  // open / new / active / reopened / unknown -> treat as open so an
  // unfamiliar status is surfaced rather than silently hidden.
  return 'open';
}

/* --- Mappers -------------------------------------------------------------- */

/**
 * A mark-up counts as an "issue" when it is a call-out or carries follow-up:
 * a revision cloud, or anything with a follow-up assignee, a label or a text
 * note. Pure geometric aids (a bare arrow, dimension, area, highlight) are
 * takeoff annotations, not issues, so they are excluded to keep the hub clean.
 */
function isMarkupIssue(m: Markup): boolean {
  if (m.assignee_id) return true;
  if (m.type === 'cloud') return true;
  if (m.label && m.label.trim()) return true;
  if (m.text && m.text.trim()) return true;
  return false;
}

export function mapMarkup(m: Markup): UnifiedIssue | null {
  // Open/active only. Resolved and archived mark-ups are done.
  if (m.status !== 'active') return null;
  if (!isMarkupIssue(m)) return null;
  const title =
    strOrNull(m.label) ?? strOrNull(m.text) ?? `${titleCaseType(m.type)} call-out`;
  return {
    id: `markup:${m.id}`,
    rawId: m.id,
    source: 'markup',
    title,
    status: 'open',
    rawStatus: m.status,
    priority: 'none',
    assignee: strOrNull(m.assignee_id),
    dueDate: null,
    createdAt: strOrNull(m.created_at),
    deepLink: markupDeepLink(m),
  };
}

export function mapPunch(p: PunchItem): UnifiedIssue | null {
  const bucket = PUNCH_BUCKET[p.status];
  if (!bucket) return null;
  return {
    id: `punch:${p.id}`,
    rawId: p.id,
    source: 'punch',
    title: strOrNull(p.title) ?? 'Punch item',
    status: bucket,
    rawStatus: p.status,
    priority: normalizePriority(p.priority),
    // The column holds a contact id as often as a name, and the hub can only
    // stub an id into `#3f2b8c1e`. Prefer the name the punch API resolved.
    assignee: strOrNull(p.assigned_to_name) ?? strOrNull(p.assigned_to),
    dueDate: strOrNull(p.due_date),
    createdAt: strOrNull(p.created_at),
    deepLink: `/punchlist?highlight=${encodeURIComponent(p.id)}`,
  };
}

export function mapNcr(n: NCR): UnifiedIssue | null {
  const bucket = NCR_BUCKET[n.status];
  if (!bucket) return null;
  const num = typeof n.ncr_number === 'number' && Number.isFinite(n.ncr_number) ? n.ncr_number : 0;
  const title = strOrNull(n.title) ?? `NCR-${String(num).padStart(3, '0')}`;
  // NCRs carry no due date and no owner field, so those stay null. Severity
  // drives priority.
  return {
    id: `ncr:${n.id}`,
    rawId: n.id,
    source: 'ncr',
    title,
    status: bucket,
    rawStatus: n.status,
    priority: NCR_PRIORITY[n.severity] ?? 'medium',
    assignee: null,
    dueDate: null,
    createdAt: strOrNull(n.created_at),
    deepLink: `/ncr?highlight=${encodeURIComponent(n.id)}`,
  };
}

export function mapClashIssue(c: ClashIssue): UnifiedIssue | null {
  const bucket = CLASH_BUCKET[c.status];
  if (!bucket) return null;
  const firstTag = Array.isArray(c.tags) && c.tags.length > 0 ? strOrNull(c.tags[0]) : null;
  const title =
    strOrNull(c.server_assigned_id) ??
    firstTag ??
    `Clash ${str(c.signature_hash).slice(0, 8)}`;
  const runId = strOrNull(c.last_seen_run_id);
  return {
    id: `clash:${c.id}`,
    rawId: c.id,
    source: 'clash',
    title,
    status: bucket,
    rawStatus: c.status,
    priority: normalizePriority(c.priority),
    assignee: strOrNull(c.assignee_id),
    dueDate: strOrNull(c.due_date),
    createdAt: strOrNull(c.created_at),
    // Smart issues are project-scoped, so link to the run where the clash was
    // last seen (opens the clash page in context), or the clash page itself.
    deepLink: runId ? `/clash?run=${encodeURIComponent(runId)}` : '/clash',
  };
}

/**
 * A complaint from the site's surroundings (noise, dust, blocked access ...).
 * Its due date is the response date, which only binds until the complaint is
 * acknowledged; after that the open work is the action, which has no date. The
 * server's own overdue flag (rule 18) raises it to high priority.
 */
export function mapNeighbourIssue(n: NeighbourIssue): UnifiedIssue | null {
  const bucket = NEIGHBOUR_BUCKET[n.state];
  if (!bucket) return null;
  const firstLine = strOrNull(str(n.description).split('\n')[0]);
  return {
    id: `neighbour:${n.id}`,
    rawId: n.id,
    source: 'neighbour',
    title: firstLine ?? `Neighbour complaint: ${str(n.kind) || 'other'}`,
    status: bucket,
    rawStatus: n.state,
    priority: n.overdue ? 'high' : 'medium',
    assignee: strOrNull(n.owner_user_id),
    dueDate: n.state === 'received' ? strOrNull(n.response_due) : null,
    createdAt: strOrNull(n.created_at) ?? strOrNull(n.reported_on),
    deepLink: `/site-logistics?neighbourIssue=${encodeURIComponent(n.id)}`,
  };
}

/**
 * BCF topic mapper. The BCF module is built in parallel, so its exact item
 * shape is not known at write time: this reads every field defensively, trying
 * the common snake_case, camelCase and BCF-XML (PascalCase) field names. When
 * the module ships a settled shape, tighten this and the deep link below.
 */
export function mapBcfTopic(raw: unknown): UnifiedIssue | null {
  if (!raw || typeof raw !== 'object') return null;
  const t = raw as Record<string, unknown>;
  const id = str(t.id ?? t.guid ?? t.topic_guid ?? t.topicGuid ?? t.Guid);
  if (!id) return null;
  const rawStatus = str(t.status ?? t.topic_status ?? t.topicStatus ?? t.TopicStatus);
  const bucket = bcfBucket(rawStatus);
  if (!bucket) return null;
  const title =
    strOrNull(t.title ?? t.topic_title ?? t.Title ?? t.name) ?? `Topic ${id.slice(0, 8)}`;
  return {
    id: `bcf:${id}`,
    rawId: id,
    source: 'bcf',
    title,
    status: bucket,
    rawStatus: rawStatus || 'open',
    priority: normalizePriority(t.priority ?? t.Priority),
    assignee: strOrNull(t.assigned_to ?? t.assignedTo ?? t.AssignedTo ?? t.assignee),
    dueDate: strOrNull(t.due_date ?? t.dueDate ?? t.DueDate),
    createdAt: strOrNull(t.created_at ?? t.creation_date ?? t.createdAt ?? t.CreationDate),
    // When the BCF module gains its own page/route, point this at it. Today
    // BCF issue exchange lives on the clash page.
    deepLink: '/clash',
  };
}

/* --- Batch helper --------------------------------------------------------- */

/**
 * Map a raw list with a per-item mapper, isolating failures. Any item whose
 * mapper throws (a shape the mapper did not expect) is dropped on its own and
 * never takes the rest of the list, or another source, down with it.
 */
export function mapEach<T>(
  rows: readonly T[] | undefined | null,
  mapper: (row: T) => UnifiedIssue | null,
): UnifiedIssue[] {
  if (!Array.isArray(rows)) return [];
  const out: UnifiedIssue[] = [];
  for (const row of rows) {
    try {
      const mapped = mapper(row);
      if (mapped) out.push(mapped);
    } catch {
      // Drop just this row. Never let one bad item break the source.
    }
  }
  return out;
}

/* --- Sorting -------------------------------------------------------------- */

export type IssueSortKey = 'due' | 'priority' | 'created';

/** Compare two ISO date strings ascending; nulls always sort last. */
function compareDateAsc(a: string | null, b: string | null): number {
  if (a === b) return 0;
  if (!a) return 1;
  if (!b) return -1;
  const ta = new Date(a).getTime();
  const tb = new Date(b).getTime();
  const va = Number.isNaN(ta) ? Number.POSITIVE_INFINITY : ta;
  const vb = Number.isNaN(tb) ? Number.POSITIVE_INFINITY : tb;
  return va - vb;
}

/**
 * Return a new, sorted copy of the list. `priority` sorts most-urgent first
 * (tie-break soonest due), `due` sorts soonest-due first (tie-break most
 * urgent), `created` sorts newest first.
 */
export function sortIssues(list: readonly UnifiedIssue[], key: IssueSortKey): UnifiedIssue[] {
  const copy = list.slice();
  copy.sort((a, b) => {
    if (key === 'priority') {
      const pr = PRIORITY_RANK[b.priority] - PRIORITY_RANK[a.priority];
      if (pr !== 0) return pr;
      return compareDateAsc(a.dueDate, b.dueDate);
    }
    if (key === 'due') {
      const dd = compareDateAsc(a.dueDate, b.dueDate);
      if (dd !== 0) return dd;
      return PRIORITY_RANK[b.priority] - PRIORITY_RANK[a.priority];
    }
    // created: newest first
    return compareDateAsc(b.createdAt, a.createdAt);
  });
  return copy;
}
