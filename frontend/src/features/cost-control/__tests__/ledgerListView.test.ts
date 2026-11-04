// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { filterSortLedger, type LedgerSort } from '../ledgerListView';

const row = (code: string, status: 'draft' | 'approved', amount: string, created_at: string | null, reason = '') => ({
  code,
  status,
  amount,
  reason,
  created_at,
});
const ROWS = [
  row('BM-001', 'approved', '100.00', '2026-01-01T00:00:00Z', 'Roof'),
  row('BM-002', 'draft', '-900.00', '2026-02-01T00:00:00Z', 'Walls'),
  row('BM-010', 'draft', '300.00', '2026-03-01T00:00:00Z', 'Roof extra'),
];
const codes = (r: typeof ROWS) => r.map((x) => x.code);

describe('filterSortLedger', () => {
  it('filters by status and by free text', () => {
    expect(codes(filterSortLedger(ROWS, { status: 'draft', query: '', sort: 'code' }))).toEqual(['BM-002', 'BM-010']);
    expect(codes(filterSortLedger(ROWS, { status: 'all', query: 'roof', sort: 'code' }))).toEqual(['BM-001', 'BM-010']);
    expect(codes(filterSortLedger(ROWS, { status: 'all', query: 'zzz', sort: 'code' }))).toEqual([]);
  });

  it('searches the extra text, such as line codes', () => {
    const out = filterSortLedger(
      ROWS,
      { status: 'all', query: '331', sort: 'code' },
      (r) => (r.code === 'BM-002' ? '331 360' : ''),
    );
    expect(codes(out)).toEqual(['BM-002']);
  });

  it('sorts by date, size (a negative change counts by its size) and code', () => {
    const s = (sort: LedgerSort) => codes(filterSortLedger(ROWS, { status: 'all', query: '', sort }));
    expect(s('newest')).toEqual(['BM-010', 'BM-002', 'BM-001']);
    expect(s('oldest')).toEqual(['BM-001', 'BM-002', 'BM-010']);
    expect(s('amount_desc')).toEqual(['BM-002', 'BM-010', 'BM-001']);
    expect(s('amount_asc')).toEqual(['BM-001', 'BM-010', 'BM-002']);
    expect(s('code')).toEqual(['BM-001', 'BM-002', 'BM-010']);
  });

  it('does not mutate its input', () => {
    const before = codes(ROWS);
    filterSortLedger(ROWS, { status: 'all', query: '', sort: 'amount_desc' });
    expect(codes(ROWS)).toEqual(before);
  });
});
