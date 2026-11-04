// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { num, type LedgerStatus } from './api';

export type LedgerSort = 'newest' | 'oldest' | 'amount_desc' | 'amount_asc' | 'code';
export type LedgerStatusFilter = 'all' | LedgerStatus;

interface Entry {
  code: string;
  status: LedgerStatus;
  reason: string;
  created_at: string | null;
}

/** Amount an entry is ranked by: what a transfer moved, or the size of a budget change. */
function size(e: { moved?: string; amount?: string }): number {
  return Math.abs(num(e.moved ?? e.amount ?? '0'));
}

/** Filter by status and free text (code, reason, line codes), then order. Returns a new array. */
export function filterSortLedger<T extends Entry & { moved?: string; amount?: string }>(
  rows: T[],
  opts: { status: LedgerStatusFilter; query: string; sort: LedgerSort },
  extraText: (row: T) => string = () => '',
): T[] {
  const q = opts.query.trim().toLowerCase();
  const out = rows.filter(
    (r) =>
      (opts.status === 'all' || r.status === opts.status) &&
      (!q || `${r.code} ${r.reason} ${extraText(r)}`.toLowerCase().includes(q)),
  );
  const stamp = (r: T) => r.created_at ?? '';
  const by: Record<LedgerSort, (a: T, b: T) => number> = {
    newest: (a, b) => stamp(b).localeCompare(stamp(a)),
    oldest: (a, b) => stamp(a).localeCompare(stamp(b)),
    amount_desc: (a, b) => size(b) - size(a),
    amount_asc: (a, b) => size(a) - size(b),
    code: (a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }),
  };
  return out.sort(by[opts.sort]);
}
