// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Bill structure helpers: levels per row (0 = position, n = section of level n),
 * suggested from the numbering, and recurring lines grouped for one-rate pricing.
 * Pure functions, no React.
 */

import { compareNames } from '@/shared/lib/collator';
import { boqApi, isSection, type Position, type RestructureRow } from './api';

/** `1`, `1.2`, `01.02.003`, `A`, `A.1`, `IV.3`, with an optional trailing dot. */
const NUMBERING = /^(?:\d{1,4}|[A-Z]|[IVXL]{2,5})(?:[.\-/](?:\d{1,4}|[A-Z]))*\.?$/;

export function isNumbering(cell: string): boolean {
  const s = cell.trim();
  return s.length > 0 && s.length <= 24 && NUMBERING.test(s);
}

function segments(ordinal: string): string[] {
  const s = ordinal.trim().replace(/\.$/, '');
  return isNumbering(s) ? s.split(/[.\-/]/) : [];
}

/** How many numbering segments an ordinal carries; 0 when it is no numbering. */
export function ordinalDepth(ordinal: string): number {
  return segments(ordinal).length;
}

/** True when `parent` numbers a chapter that `child` sits in (`1.2` before `1.2.3`). */
export function isOrdinalPrefix(parent: string, child: string): boolean {
  const a = segments(parent);
  const b = segments(child);
  return a.length > 0 && b.length > a.length && a.every((seg, i) => seg.toLowerCase() === b[i]!.toLowerCase());
}

type Row = Pick<Position, 'id' | 'parent_id' | 'sort_order' | 'ordinal' | 'unit' | 'quantity' | 'unit_rate'>;

/** Rows in reading order: each section followed by its subtree, siblings by sort order. */
export function documentOrder<T extends Row>(positions: readonly T[]): T[] {
  const ids = new Set(positions.map((p) => p.id));
  const children = new Map<string | null, T[]>();
  for (const p of positions) {
    const key = p.parent_id && ids.has(p.parent_id) ? p.parent_id : null;
    const list = children.get(key) ?? [];
    list.push(p);
    children.set(key, list);
  }
  for (const list of children.values()) list.sort((a, b) => a.sort_order - b.sort_order);
  const out: T[] = [];
  const seen = new Set<string>();
  const walk = (key: string | null) => {
    for (const p of children.get(key) ?? []) {
      if (seen.has(p.id)) continue;
      seen.add(p.id);
      out.push(p);
      walk(p.id);
    }
  };
  walk(null);
  return out;
}

const isHeader = (p: Pick<Position, 'unit' | 'quantity' | 'unit_rate'>) =>
  isSection(p) && !Number(p.quantity) && !Number(p.unit_rate);

/** The level each row has today, in document order. */
export function currentLevels<T extends Row>(ordered: readonly T[]): number[] {
  const byId = new Map(ordered.map((p) => [p.id, p]));
  return ordered.map((p) => {
    if (!isHeader(p)) return 0;
    let depth = 1;
    let parent = p.parent_id ? byId.get(p.parent_id) : undefined;
    while (parent && depth < 32) {
      depth++;
      parent = parent.parent_id ? byId.get(parent.parent_id) : undefined;
    }
    return depth;
  });
}

/**
 * Levels suggested for a flat bill. A row is a title when it is already a
 * section, carries no unit, or numbers a chapter the next row sits in
 * (`1.2` followed by `1.2.1`). A title's level is its numbering depth.
 */
export function suggestLevels<T extends Row>(ordered: readonly T[]): number[] {
  const current = currentLevels(ordered);
  return ordered.map((p, i) => {
    const next = ordered[i + 1];
    const title = current[i]! > 0 || !p.unit?.trim() || (next !== undefined && isOrdinalPrefix(p.ordinal, next.ordinal));
    if (!title) return 0;
    return ordinalDepth(p.ordinal) || current[i] || 1;
  });
}

export interface RecurringLine {
  key: string;
  description: string;
  unit: string;
  ids: string[];
  rates: number[];
  /** The occurrences carry more than one unit rate. */
  drifting: boolean;
}

/** Lines that recur across the bill (same description and unit), most frequent first. */
export function recurringLines(positions: ReadonlyArray<Pick<Position, 'id' | 'description' | 'unit' | 'quantity' | 'unit_rate'>>): RecurringLine[] {
  const groups = new Map<string, RecurringLine>();
  for (const p of positions) {
    if (isHeader(p)) continue;
    const description = (p.description ?? '').trim().replace(/\s+/g, ' ');
    if (!description) continue;
    const unit = (p.unit ?? '').trim();
    const key = `${description.toLowerCase()}\u0000${unit.toLowerCase()}`;
    const g = groups.get(key) ?? { key, description, unit, ids: [], rates: [], drifting: false };
    g.ids.push(p.id);
    g.rates.push(Number(p.unit_rate) || 0);
    groups.set(key, g);
  }
  const out = [...groups.values()].filter((g) => g.ids.length > 1);
  for (const g of out) g.drifting = new Set(g.rates.map((r) => Math.round(r * 10000))).size > 1;
  return out.sort((a, b) => b.ids.length - a.ids.length || compareNames(a.description, b.description));
}

/**
 * The restructure request after a paste: the bill's existing rows keep their
 * levels, the pasted rows follow at the end with the levels set in the preview.
 */
export async function pastedStructure(
  boqId: string,
  created: ReadonlyArray<Pick<Position, 'id'>>,
  pasted: ReadonlyArray<{ level: number }>,
): Promise<RestructureRow[]> {
  const fresh = await boqApi.get(boqId);
  const createdIds = new Set(created.map((p) => p.id));
  const existing = documentOrder(fresh.positions.filter((p) => !createdIds.has(p.id)));
  const levels = currentLevels(existing);
  return [
    ...existing.map((p, i) => ({ position_id: p.id, level: levels[i]! })),
    ...created.map((p, i) => ({ position_id: p.id, level: pasted[i]?.level ?? 0 })),
  ];
}
