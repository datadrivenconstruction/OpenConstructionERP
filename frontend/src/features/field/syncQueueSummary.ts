// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure derivations for the offline / pending-sync review panel.
 *
 * The PWA offline mutation queue (`shared/lib/offline/mutationQueue.ts`) stores
 * each captured write as a {@link QueuedOp}. An op that has never been attempted
 * sits at `retries === 0` (genuinely *pending*); an op that has come back from a
 * drain with a transient failure (network / 5xx) is kept in the queue with an
 * incremented `retries` and is therefore *failing* - it will keep being retried
 * on the next drain until it succeeds or hits the queue's retry ceiling.
 *
 * These helpers turn the raw op list into the shape the review UI renders:
 *   - a derived status per op (pending vs failing),
 *   - a human label for the op's logical `kind` and HTTP `method`,
 *   - counts + grouping for the panel header and section lists.
 *
 * Everything here is pure and framework-free so it is unit-tested in jsdom with
 * no store, no DB and no React. The component layer formats timestamps and wires
 * the actions; this module only derives.
 */

import type { QueuedOp } from '@/shared/lib/offline';

/** Derived display status of a queued op (richer than the raw `retries` field). */
export type SyncItemStatus = 'pending' | 'failing';

/** A queued op decorated with its derived status, ready for the review list. */
export interface SyncQueueItem {
  /** The idempotency key; also the stable React list key + action target. */
  clientOpId: string;
  /** Logical target, e.g. `field.diary.entry` (used for the type label). */
  kind: string;
  /** HTTP verb of the captured write. */
  method: QueuedOp['method'];
  /** API path of the captured write. */
  path: string;
  /** Epoch ms when the op was captured on the device. */
  queuedAt: number;
  /** Failed replay attempts so far (0 = never attempted). */
  retries: number;
  /** Derived status: never-attempted vs transiently-failing. */
  status: SyncItemStatus;
}

/** Aggregate counts + ordered item list for the review panel. */
export interface SyncQueueSummary {
  /** Every op, decorated and sorted (failing first, then oldest-first). */
  items: SyncQueueItem[];
  /** Total ops awaiting sync (pending + failing). */
  total: number;
  /** Ops never attempted yet. */
  pending: number;
  /** Ops that have failed at least one transient attempt. */
  failing: number;
  /** True when there is nothing to sync (drives the empty state). */
  isEmpty: boolean;
}

/** A `kind` bucket with its label and member items (for grouped rendering). */
export interface SyncQueueGroup {
  kind: string;
  label: string;
  items: SyncQueueItem[];
  failing: number;
}

/** Derive the display status of a single op. */
export function deriveStatus(op: Pick<QueuedOp, 'retries'>): SyncItemStatus {
  return op.retries > 0 ? 'failing' : 'pending';
}

/**
 * Turn a raw `kind` token (`field.diary.entry`, `daily_diary`, `field_report`)
 * into a short, human, Title Case label. Falls back gracefully for unknown
 * kinds by humanising the token, so a new op kind never renders as a raw slug.
 *
 * Known kinds are mapped explicitly so the label reads naturally; anything else
 * is derived from the last dotted segment with separators normalised to spaces.
 */
export function kindLabel(kind: string): string {
  const known: Record<string, string> = {
    'field.diary.entry': 'Diary entry',
    'field.diary.activity': 'Time entry',
    'field.crew.punch': 'Crew punch',
    field_report: 'Field report',
    daily_diary: 'Daily diary',
  };
  const hit = known[kind];
  if (hit) return hit;

  // Unknown kind: humanise the last meaningful segment.
  const tail = kind.split('.').filter(Boolean).pop() ?? kind;
  const words = tail
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1));
  const label = words.join(' ').trim();
  return label || kind;
}

/**
 * Stable sort for the review list: failing ops first (they need attention), then
 * by capture time oldest-first within each status (FIFO replay order, so the
 * next op the queue will send is at the top of the pending group). Ties break on
 * `clientOpId` for determinism. Does not mutate the input.
 */
export function sortForReview(items: readonly SyncQueueItem[]): SyncQueueItem[] {
  const rank: Record<SyncItemStatus, number> = { failing: 0, pending: 1 };
  return [...items].sort((a, b) => {
    if (a.status !== b.status) return rank[a.status] - rank[b.status];
    if (a.queuedAt !== b.queuedAt) return a.queuedAt - b.queuedAt;
    return a.clientOpId < b.clientOpId ? -1 : a.clientOpId > b.clientOpId ? 1 : 0;
  });
}

/**
 * Build the full summary the review panel renders from the raw queue ops.
 * Pure: same input always yields the same output.
 */
export function summariseQueue(ops: readonly QueuedOp[]): SyncQueueSummary {
  const items: SyncQueueItem[] = ops.map((op) => ({
    clientOpId: op.clientOpId,
    kind: op.kind,
    method: op.method,
    path: op.path,
    queuedAt: op.queuedAt,
    retries: op.retries,
    status: deriveStatus(op),
  }));
  const sorted = sortForReview(items);
  const failing = sorted.filter((i) => i.status === 'failing').length;
  return {
    items: sorted,
    total: sorted.length,
    pending: sorted.length - failing,
    failing,
    isEmpty: sorted.length === 0,
  };
}

/**
 * Group decorated items by `kind`, preserving the review sort order both for the
 * groups (a group's position follows its first item) and within each group.
 * Used for the optional grouped view in the panel.
 */
export function groupByKind(items: readonly SyncQueueItem[]): SyncQueueGroup[] {
  const ordered = sortForReview(items);
  const groups = new Map<string, SyncQueueGroup>();
  for (const item of ordered) {
    let group = groups.get(item.kind);
    if (!group) {
      group = { kind: item.kind, label: kindLabel(item.kind), items: [], failing: 0 };
      groups.set(item.kind, group);
    }
    group.items.push(item);
    if (item.status === 'failing') group.failing += 1;
  }
  return [...groups.values()];
}

/**
 * Format the capture time as a short relative string ("just now", "5 min ago",
 * "2 h ago", "3 d ago"). Pure given an explicit `now` so it is timezone- and
 * clock-stable in tests. A future timestamp (clock skew) clamps to "just now".
 */
export function formatRelativeTime(queuedAt: number, now: number): string {
  const deltaMs = now - queuedAt;
  if (deltaMs < 45_000) return 'just now';
  const mins = Math.floor(deltaMs / 60_000);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(deltaMs / 3_600_000);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(deltaMs / 86_400_000);
  return `${days} d ago`;
}
