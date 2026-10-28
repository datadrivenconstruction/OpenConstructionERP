// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * diffGrouping — pure transforms over the backend BIM model diff.
 *
 * The backend (`bim_hub` service `compute_diff`) returns a flat
 * `diff_details` with `added` / `deleted` / `modified` arrays keyed by
 * `stable_id`. This module groups those entries by category (element_type,
 * which is the trade-level bucket the BIM viewer already colours by) and
 * formats the per-element field deltas for display. It does NOT recompute or
 * mutate the diff — read-only consumption only.
 */

import type {
  BIMModelDiff,
  BIMDiffModifiedEntry,
  BIMDiffSimpleEntry,
} from './api';

export type DiffChangeType = 'added' | 'deleted' | 'modified';

/** A single element row in the grouped diff list. */
export interface DiffElementRow {
  stableId: string;
  changeType: DiffChangeType;
  category: string;
  name: string | null;
  /** Human-readable per-field deltas — only for `modified`. */
  fieldDeltas: DiffFieldDelta[];
}

export interface DiffFieldDelta {
  field: string;
  oldText: string;
  newText: string;
}

/** One category bucket with its counts and member rows. */
export interface DiffCategoryGroup {
  category: string;
  added: number;
  deleted: number;
  modified: number;
  total: number;
  rows: DiffElementRow[];
}

export interface GroupedDiff {
  groups: DiffCategoryGroup[];
  totals: { added: number; deleted: number; modified: number };
  /** Stable-id → change type, for fast scene colouring. */
  changeByStableId: Map<string, DiffChangeType>;
}

const UNCATEGORISED = 'Uncategorised';

function categoryOf(
  entry: BIMDiffSimpleEntry | BIMDiffModifiedEntry,
): string {
  const t = entry.element_type;
  if (t && t.trim()) return t.trim();
  return UNCATEGORISED;
}

/** Stringify an arbitrary diff value compactly for the UI. Objects/arrays
 *  are JSON-encoded and truncated so a 200-key property bag delta doesn't
 *  blow out the panel. */
export function formatDiffValue(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'string') return v === '' ? '—' : v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  try {
    const json = JSON.stringify(v);
    return json.length > 120 ? `${json.slice(0, 117)}…` : json;
  } catch {
    return String(v);
  }
}

function modifiedToRow(entry: BIMDiffModifiedEntry): DiffElementRow {
  return {
    stableId: entry.stable_id,
    changeType: 'modified',
    category: categoryOf(entry),
    name: null,
    fieldDeltas: (entry.changes ?? []).map((c) => ({
      field: c.field,
      oldText: formatDiffValue(c.old),
      newText: formatDiffValue(c.new),
    })),
  };
}

function simpleToRow(
  entry: BIMDiffSimpleEntry,
  changeType: 'added' | 'deleted',
): DiffElementRow {
  return {
    stableId: entry.stable_id,
    changeType,
    category: categoryOf(entry),
    name: entry.name ?? null,
    fieldDeltas: [],
  };
}

/**
 * Group a model diff by category/trade. Categories are sorted by total
 * change count (busiest first); rows within a category are ordered
 * deleted → modified → added so removals surface at the top of each group.
 */
export function groupModelDiff(diff: BIMModelDiff): GroupedDiff {
  const details = diff.diff_details;
  const rows: DiffElementRow[] = [];
  const changeByStableId = new Map<string, DiffChangeType>();

  if (details) {
    for (const e of details.deleted ?? []) {
      rows.push(simpleToRow(e, 'deleted'));
      changeByStableId.set(e.stable_id, 'deleted');
    }
    for (const e of details.modified ?? []) {
      rows.push(modifiedToRow(e));
      changeByStableId.set(e.stable_id, 'modified');
    }
    for (const e of details.added ?? []) {
      rows.push(simpleToRow(e, 'added'));
      changeByStableId.set(e.stable_id, 'added');
    }
  }

  const byCategory = new Map<string, DiffElementRow[]>();
  for (const row of rows) {
    const list = byCategory.get(row.category);
    if (list) list.push(row);
    else byCategory.set(row.category, [row]);
  }

  const order: Record<DiffChangeType, number> = {
    deleted: 0,
    modified: 1,
    added: 2,
  };
  const groups: DiffCategoryGroup[] = [];
  for (const [category, list] of byCategory) {
    const sorted = [...list].sort(
      (a, b) => order[a.changeType] - order[b.changeType],
    );
    groups.push({
      category,
      added: list.filter((r) => r.changeType === 'added').length,
      deleted: list.filter((r) => r.changeType === 'deleted').length,
      modified: list.filter((r) => r.changeType === 'modified').length,
      total: list.length,
      rows: sorted,
    });
  }
  groups.sort(
    (a, b) => b.total - a.total || a.category.localeCompare(b.category),
  );

  return {
    groups,
    totals: {
      added: diff.diff_summary.added,
      deleted: diff.diff_summary.deleted,
      modified: diff.diff_summary.modified,
    },
    changeByStableId,
  };
}
