// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure, framework-free helpers for the unified inbox.
 *
 * Kept separate from the React components so the ordering / grouping / title
 * derivation can be unit-tested with vitest and reused without pulling in the
 * component tree. No imports from React or the API client here.
 */
import type { InboxItem, InboxKind, InboxSeverity } from './api';
import { compareNames } from '@/shared/lib/collator';

/** Severity rank - higher sorts first when timestamps tie. */
export const SEVERITY_RANK: Record<InboxSeverity, number> = {
  critical: 3,
  warning: 2,
  info: 1,
};

/** Clamp an arbitrary string to one of the three known severities. */
export function normalizeSeverity(value: string | null | undefined): InboxSeverity {
  if (value === 'critical' || value === 'warning' || value === 'info') return value;
  return 'info';
}

/**
 * Deterministic newest-first ordering with a severity then id tiebreak.
 *
 * The backend already sorts, but re-sorting client-side is a cheap safety net
 * (e.g. if items from two cached pages are ever concatenated) and keeps the
 * ordering logic unit-testable. ``created_at`` is compared lexicographically:
 * for the ISO-8601 UTC strings every source emits, that is chronological.
 * Missing timestamps sort last. Pure: does not mutate the input array.
 */
export function sortInboxItems(items: readonly InboxItem[]): InboxItem[] {
  return [...items].sort((a, b) => {
    const ca = a.created_at ?? '';
    const cb = b.created_at ?? '';
    if (ca !== cb) return ca < cb ? 1 : -1; // newest (greater string) first
    const sa = SEVERITY_RANK[normalizeSeverity(a.severity)];
    const sb = SEVERITY_RANK[normalizeSeverity(b.severity)];
    if (sa !== sb) return sb - sa; // higher severity first
    // Fully deterministic final tiebreak on id.
    if (a.id !== b.id) return a.id < b.id ? 1 : -1;
    return 0;
  });
}

/** Count how many items are pending approvals (vs alerts). */
export function countApprovals(items: readonly InboxItem[]): number {
  return items.reduce((n, it) => (it.kind === 'approval' ? n + 1 : n), 0);
}

/* ── Client-side triage filters ────────────────────────────────────────────
 * The full inbox page turns the raw list into a real triage surface by
 * filtering on three dimensions the API already carries on every item: kind
 * (approval vs alert), the originating project, and severity. Everything is
 * derived from data already fetched - no extra endpoint. The predicates are
 * pure so they can be unit-tested and reused by both the page (for counts) and
 * the panel (for the rendered subset).
 * ------------------------------------------------------------------------- */

/** Kind selector: either everything or one of the two streams. */
export type InboxKindFilter = 'all' | InboxKind;
/** Severity selector: either everything or one specific level. */
export type InboxSeverityFilter = 'all' | InboxSeverity;

/** The active triage filter. ``'all'`` on any axis means "don't narrow it". */
export interface InboxFilter {
  kind: InboxKindFilter;
  /** A project id, or ``'all'`` for every project. */
  projectId: string;
  severity: InboxSeverityFilter;
}

/** The neutral filter - matches every item. */
export const ALL_INBOX_FILTER: InboxFilter = {
  kind: 'all',
  projectId: 'all',
  severity: 'all',
};

/** True when the filter narrows the list on at least one axis. */
export function isInboxFiltered(filter: InboxFilter): boolean {
  return filter.kind !== 'all' || filter.projectId !== 'all' || filter.severity !== 'all';
}

/** Does a single item satisfy every active axis of the filter? */
export function matchesInboxFilter(item: InboxItem, filter: InboxFilter): boolean {
  if (filter.kind !== 'all' && item.kind !== filter.kind) return false;
  if (filter.projectId !== 'all' && (item.project_id ?? '') !== filter.projectId) return false;
  if (filter.severity !== 'all' && normalizeSeverity(item.severity) !== filter.severity) {
    return false;
  }
  return true;
}

/** Return the subset of items matching the filter (order preserved, pure). */
export function filterInboxItems(
  items: readonly InboxItem[],
  filter: InboxFilter,
): InboxItem[] {
  return items.filter((it) => matchesInboxFilter(it, filter));
}

/**
 * Distinct projects present in the list, for the project filter dropdown.
 *
 * Keyed by ``project_id``; the label falls back to the id when a name is
 * missing. Items with no project are skipped (they live under "All projects").
 * Sorted by display name for a stable, readable menu.
 */
export function distinctInboxProjects(
  items: readonly InboxItem[],
): { id: string; name: string }[] {
  const byId = new Map<string, string>();
  for (const it of items) {
    const id = it.project_id;
    if (typeof id === 'string' && id.length > 0 && !byId.has(id)) {
      byId.set(id, (it.project_name ?? '').trim() || id);
    }
  }
  return Array.from(byId, ([id, name]) => ({ id, name })).sort((a, b) =>
    compareNames(a.name, b.name),
  );
}

/** Distinct severities present, ordered most-severe first (for the dropdown). */
export function distinctInboxSeverities(items: readonly InboxItem[]): InboxSeverity[] {
  const present = new Set<InboxSeverity>();
  for (const it of items) present.add(normalizeSeverity(it.severity));
  const order: InboxSeverity[] = ['critical', 'warning', 'info'];
  return order.filter((s) => present.has(s));
}

/**
 * Resolve the display title for an item.
 *
 * Returns ``{ key, defaultValue }`` so the caller can feed it straight into
 * i18next's ``t(key, { defaultValue, ...ctx })``. When the item carries an
 * i18n ``title_key`` we use it (with ``title`` as the English fallback); a
 * missing key degrades to the raw ``title`` string, and a totally empty item
 * degrades to a generic label key. Never returns an empty key (i18next
 * ``t('')`` is a no-op that renders blank).
 */
export function resolveTitle(item: Pick<InboxItem, 'title' | 'title_key'>): {
  key: string;
  defaultValue: string;
} {
  const key =
    typeof item.title_key === 'string' && item.title_key.trim().length > 0
      ? item.title_key
      : '';
  const fallback =
    typeof item.title === 'string' && item.title.trim().length > 0 ? item.title : '';
  if (key) {
    return { key, defaultValue: fallback || key };
  }
  if (fallback) {
    // No i18n key - render the literal title via a stable passthrough key so
    // i18next still receives a non-empty key.
    return { key: 'inbox.item_title_raw', defaultValue: fallback };
  }
  return { key: 'inbox.item_untitled', defaultValue: 'Action required' };
}

/**
 * Human "x ago" string. Takes the i18next ``t`` so the units are localised.
 *
 * Mirrors the NotificationBell formatter; extracted here so the inbox panel
 * and any future surface share one implementation. Returns an empty string
 * for a missing / unparseable timestamp (callers can then omit the row's
 * time element entirely).
 */
export function formatTimeAgo(
  dateStr: string | null | undefined,
  t: (key: string, opts?: Record<string, unknown>) => string,
  now: number = Date.now(),
): string {
  if (!dateStr) return '';
  const ms = new Date(dateStr).getTime();
  if (!Number.isFinite(ms)) return '';
  const diff = now - ms;
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return t('notifications.just_now', { defaultValue: 'Just now' });
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60)
    return t('time.minutes_ago', { defaultValue: '{{count}}m ago', count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('time.hours_ago', { defaultValue: '{{count}}h ago', count: hours });
  const days = Math.floor(hours / 24);
  return t('time.days_ago', { defaultValue: '{{count}}d ago', count: days });
}
