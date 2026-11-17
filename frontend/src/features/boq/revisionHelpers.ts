// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers for the revision navigator and the snapshot View / Compare
 * panels of Version History. No React, no network.
 */
import type { SnapshotCompareResponse } from './api';

/** The two picked revisions as [older, newer], in lineage order. */
export function compareOrder(
  revisions: ReadonlyArray<{ boq_id: string }>,
  a: string,
  b: string,
): [string, string] {
  const ia = revisions.findIndex((r) => r.boq_id === a);
  const ib = revisions.findIndex((r) => r.boq_id === b);
  return ia <= ib ? [a, b] : [b, a];
}

export type Author =
  | { kind: 'user'; name: string }
  | { kind: 'unknown' }
  | { kind: 'unavailable' };

/**
 * Who made a logged change. An entry with no recorded actor is
 * `unavailable`: attribution is never inferred from the bill's creator.
 */
export function authorOf(entry: { user_id?: string | null; user_name?: string | null }): Author {
  if (!entry.user_id) return { kind: 'unavailable' };
  if (entry.user_name) return { kind: 'user', name: entry.user_name };
  return { kind: 'unknown' };
}

export interface FieldDelta {
  field: string;
  before: unknown;
  after: unknown;
}

export interface SnapshotDiffRow {
  kind: 'added' | 'removed' | 'changed';
  ordinal: string;
  description: string;
  changes: FieldDelta[];
}

/** Changed lines first, then additions, then removals; unchanged lines never appear. */
export function snapshotDiffRows(resp: SnapshotCompareResponse): SnapshotDiffRow[] {
  const rows: SnapshotDiffRow[] = [];
  for (const p of resp.changed ?? []) {
    const changes: FieldDelta[] = [];
    for (const [field, raw] of Object.entries(p.fields ?? {})) {
      if (raw && typeof raw === 'object' && 'old' in raw && 'new' in raw) {
        const rec = raw as { old: unknown; new: unknown };
        changes.push({ field, before: rec.old, after: rec.new });
      }
    }
    rows.push({ kind: 'changed', ordinal: p.ordinal, description: p.description, changes });
  }
  for (const p of resp.added ?? []) {
    rows.push({
      kind: 'added',
      ordinal: p.ordinal,
      description: p.description,
      changes: Object.entries(p.fields ?? {}).map(([field, v]) => ({ field, before: null, after: v })),
    });
  }
  for (const p of resp.removed ?? []) {
    rows.push({
      kind: 'removed',
      ordinal: p.ordinal,
      description: p.description,
      changes: Object.entries(p.fields ?? {}).map(([field, v]) => ({ field, before: v, after: null })),
    });
  }
  return rows;
}

export interface SnapshotPreviewRow {
  ordinal: string;
  description: string;
  unit: string;
  quantity: number | null;
  unitRate: number | null;
  total: number | null;
  isSection: boolean;
}

export interface SnapshotPreview {
  rows: SnapshotPreviewRow[];
  directTotal: number;
  markupCount: number;
}

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** A read-only view of a snapshot payload, in bill order. Reads, never mutates, `data`. */
export function snapshotPreview(data: Record<string, unknown> | null | undefined): SnapshotPreview {
  const positions = Array.isArray(data?.positions) ? (data!.positions as Array<Record<string, unknown>>) : [];
  const markups = Array.isArray(data?.markups) ? (data!.markups as unknown[]) : [];
  const ordered = [...positions].sort((a, b) => (num(a.sort_order) ?? 0) - (num(b.sort_order) ?? 0));
  let directTotal = 0;
  const rows = ordered.map((p) => {
    const unit = typeof p.unit === 'string' ? p.unit : '';
    const isSection = unit.trim() === '' || unit === 'section';
    const total = num(p.total);
    if (!isSection && total !== null) directTotal += total;
    return {
      ordinal: String(p.ordinal ?? ''),
      description: String(p.description ?? ''),
      unit,
      quantity: num(p.quantity),
      unitRate: num(p.unit_rate),
      total,
      isSection,
    };
  });
  return { rows, directTotal: Math.round(directTotal * 100) / 100, markupCount: markups.length };
}
