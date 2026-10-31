// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import type { Board, BidQuote, BidRow } from './api';
import { changedCells, countdown, parseAmount, recompute } from './logic';

function quote(id: string, amount: string, extra: Partial<BidQuote> = {}): BidQuote {
  return {
    id, source: 'late', channel: 'phone', vendor: id, amount, source_amount: null, currency: 'EUR', fx_rate: '1',
    received_at: null, note: '', exclusions: [], as_quoted: '0', adjusted: '0', open_exclusions: 0,
    is_chosen: false, rev: 1, ...extra,
  };
}

function row(id: string, plug: string, quotes: BidQuote[], chosen: string | null = null): BidRow {
  return {
    id, bid_package_id: null, name: id, kind: 'subcontract', plug_amount: plug, chosen_quote_id: chosen,
    value: '0', delta_vs_plug: '0', suggestion: null, quotes, rev: 1,
  };
}

function board(rows: BidRow[], pct: [string, string, string] = ['0', '0', '0']): Board {
  return {
    id: 'b', project_id: 'p', tender_id: 't', tender_name: 'T', deadline: null, currency: 'EUR', status: 'open',
    version: 1, markup_rev: 1, overhead_pct: pct[0], risk_pct: pct[1], profit_pct: pct[2], stale_days: 30,
    deviation_pct_limit: '10', rows, events: [], findings: [], snapshots: [],
    totals: {
      direct: '0', overhead: '0', risk: '0', profit: '0', markup: '0', bid_total: '0', estimate_direct: '0',
      estimate_total: '0', vs_estimate: '0', last_snapshot_total: '150000.00', delta_vs_snapshot: null,
    },
  };
}

describe('bid day optimistic arithmetic', () => {
  it('matches the server: chosen adjusted or plug, markups, snapshot delta', () => {
    const b = recompute(
      board(
        [
          row('concrete', '100000', [quote('a', '90000')], 'a'),
          row('steel', '50000', []),
        ],
        ['8', '2', '5'],
      ),
    );
    expect(b.totals.direct).toBe('140000.00');
    expect(b.totals.profit).toBe('7700.00');
    expect(b.totals.bid_total).toBe('161700.00');
    expect(b.totals.delta_vs_snapshot).toBe('11700.00');
    expect(b.rows[0]?.delta_vs_plug).toBe('-10000.00');
  });

  it('adds only plugged exclusions and converts currency', () => {
    const q = quote('a', '1000', {
      fx_rate: '1.1',
      exclusions: [
        { id: '1', text: 'Crane', status: 'plugged', plug_amount: '250' },
        { id: '2', text: 'Scaffold', status: 'open', plug_amount: '999' },
      ],
    });
    const b = recompute(board([row('r', '0', [q], 'a')]));
    expect(b.rows[0]?.quotes[0]?.as_quoted).toBe('1100.00');
    expect(b.rows[0]?.quotes[0]?.adjusted).toBe('1350.00');
    expect(b.rows[0]?.quotes[0]?.open_exclusions).toBe(1);
  });

  it('reports which cells moved and by how much', () => {
    const before = recompute(board([row('r', '100', [quote('a', '90')], 'a')]));
    const after = recompute(board([row('r', '100', [quote('a', '72')], 'a')]));
    const diff = changedCells(before, after);
    expect(diff.get('quote:a')).toBe(-1800);
    expect(diff.get('row:r')).toBe(-1800);
    expect(diff.get('total')).toBe(-1800);
  });
});

describe('parseAmount', () => {
  it.each([
    ['1 250 000', '1250000'],
    ['1,250,000.50', '1250000.50'],
    ['1.250.000,50', '1250000.50'],
    ['-18400', '-18400'],
    ['12,5', '12.5'],
    ['abc', null],
  ])('%s -> %s', (raw, out) => {
    expect(parseAmount(raw)).toBe(out);
  });
});

describe('countdown', () => {
  it('counts down and flags an overdue deadline', () => {
    const now = Date.parse('2026-10-31T12:00:00Z');
    const c = countdown('2026-10-31T15:30:00Z', now);
    expect(c?.hours).toBe(3);
    expect(c?.minutes).toBe(30);
    expect(c?.overdue).toBe(false);
    expect(countdown('2026-10-31T11:00:00Z', now)?.overdue).toBe(true);
    expect(countdown(null, now)).toBeNull();
  });
});
