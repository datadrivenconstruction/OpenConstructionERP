// Design module (ERP side of the design editor link).
/** Types and decisions of the acceptance screen: what the impact endpoint returns and who may do what. */

import type { RevisionView } from './revisions';

export interface ImpactRow {
  rule: string;
  label: string;
  cost_group: string;
  unit: string;
  position_id: string | null;
  ordinal: string | null;
  new_position: boolean;
  current_quantity: string;
  model_quantity_now: string | null;
  model_quantity_new: string;
  new_quantity: string;
  quantity_delta: string;
  override: boolean;
  override_quantity: string | null;
  unit_rate: string;
  cost_delta: string;
  flags: string[];
  elements: { before: number; after: number; added: string[]; removed: string[]; added_count: number; removed_count: number };
}

export interface Impact {
  schema: 'ddc-impact/1';
  revision_id: string;
  /** False when the project has no estimate yet: there is nothing to compare. */
  estimate: boolean;
  rows: ImpactRow[];
  model_delta_by_type: unknown[];
  totals?: { current: string; after: string; delta: string; unpriced_positions: number };
}

export const isZero = (value: string): boolean => Number(value) === 0;

/** Rows that need a person first: overrides, positions that now match nothing, anything flagged. */
export function attentionRows(rows: ImpactRow[]): ImpactRow[] {
  return rows.filter((r) => r.override || r.flags.length > 0);
}

/** Rows whose quantity or cost moves, plus new positions; unchanged ones are only counted. */
export function movingRows(rows: ImpactRow[]): ImpactRow[] {
  return rows.filter((r) => r.new_position || !isZero(r.quantity_delta) || !isZero(r.cost_delta));
}

export type Blocker = 'access' | 'role' | 'status' | 'waiting' | 'stale';

/** These stop an accept only: a revision that cannot be accepted can still be rejected and cleared away. */
export const ACCEPT_ONLY: readonly Blocker[] = ['waiting', 'stale'];

/**
 * Why the decision buttons are off, in the order a person can fix them.
 * `latestPublished` is the accepted revision the pending one has to build on. A revision built on one that still
 * waits is next in line (`waiting`); one built on anything else can no longer be accepted (`stale`).
 */
export function blockers(
  rev: RevisionView | null,
  canAccept: boolean | undefined,
  latestPublished: RevisionView | null,
  all: RevisionView[] = [],
): Blocker[] {
  const out: Blocker[] = [];
  if (!rev) return out;
  if (canAccept === false) out.push('role');
  if (rev.status !== 'shared') out.push('status');
  else if ((latestPublished?.revision_id ?? null) !== rev.parent_revision_id) {
    const parent = all.find((r) => r.revision_id === rev.parent_revision_id);
    out.push(parent?.status === 'shared' ? 'waiting' : 'stale');
  }
  return out;
}

/** The revision a pending one is judged against: the accepted one it is based on. */
export function baseOf(rev: RevisionView, all: RevisionView[]): RevisionView | null {
  return all.find((r) => r.revision_id === rev.parent_revision_id) ?? null;
}

/** Pending revisions, oldest first: the order a manager should work through them. */
export function pending(all: RevisionView[]): RevisionView[] {
  return all.filter((r) => r.status === 'shared').sort((a, b) => a.number - b.number);
}

/** Money as a plain grouped number; the unit is shown next to it. Never rounds the sign away. */
export function money(value: string, locale?: string): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return n.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** A quantity in the page language: no padded zeros, at most 3 decimals. */
export function qty(value: string, locale?: string): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return n.toLocaleString(locale, { minimumFractionDigits: 0, maximumFractionDigits: 3 });
}

const UNITS: Record<string, string> = { m2: 'm²', m3: 'm³', 'm^2': 'm²', 'm^3': 'm³' };

const PIECES: Record<string, string> = { ru: 'шт', de: 'Stk' };

/** Unit with its exponent as a superscript, pieces in the page language; unknown units are shown as they are. */
export function unitLabel(unit: string, locale?: string): string {
  const key = unit.trim().toLowerCase();
  if (key === 'pcs' || key === 'pc') return PIECES[(locale ?? '').slice(0, 2)] ?? unit;
  return UNITS[key] ?? unit;
}

/**
 * True when the estimate falls only because positions lost their model match: a total of 0 after a non-zero
 * one, or any flagged "no match" position whose cost goes down. That is a warning, never a saving.
 */
export function collapsedByNoMatch(impact: Impact): boolean {
  const t = impact.totals;
  const noMatch = impact.rows.some((r) => r.flags.includes('no_match') && Number(r.cost_delta) < 0);
  return noMatch || (!!t && Number(t.after) === 0 && Number(t.current) !== 0);
}
