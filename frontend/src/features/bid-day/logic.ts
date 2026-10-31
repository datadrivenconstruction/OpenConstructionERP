// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Client copy of the bid day arithmetic, used only for the optimistic figure
 * shown until the server answers. Works in integer cents so a long board does
 * not drift; the server's Decimal result always replaces it.
 */
import type { Board, BidQuote, BidRow, Exclusion, Totals } from './api';

export function toCents(v: string | number | null | undefined): number {
  if (v === null || v === undefined || v === '') return 0;
  const n = typeof v === 'number' ? v : Number(String(v).replace(/\s/g, ''));
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

export function fromCents(c: number): string {
  const sign = c < 0 ? '-' : '';
  const abs = Math.abs(Math.round(c));
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, '0')}`;
}

/** Parse what an estimator types: "1 250 000", "1,250,000.50", "1.250.000,50", "-18400". */
export function parseAmount(raw: string): string | null {
  let s = raw.trim().replace(/[\s  ']/g, '');
  if (!s) return null;
  const lastComma = s.lastIndexOf(',');
  const lastDot = s.lastIndexOf('.');
  if (lastComma > -1 && lastDot > -1) {
    const dec = lastComma > lastDot ? ',' : '.';
    s = s.split(dec === ',' ? '.' : ',').join('').replace(dec, '.');
  } else if (lastComma > -1) {
    const tail = s.length - lastComma - 1;
    s = s.split(',').length === 2 && tail !== 3 ? s.replace(',', '.') : s.split(',').join('');
  } else if (lastDot > -1 && s.split('.').length > 2) {
    s = s.split('.').join('');
  }
  if (!/^-?\d+(\.\d+)?$/.test(s)) return null;
  return s;
}

export function plugCents(exclusions: Exclusion[]): number {
  return exclusions.reduce((acc, x) => acc + (x.status === 'plugged' ? toCents(x.plug_amount) : 0), 0);
}

export function asQuotedCents(q: Pick<BidQuote, 'amount' | 'fx_rate'>): number {
  return Math.round(toCents(q.amount) * Number(q.fx_rate || '1'));
}

export function adjustedCents(q: Pick<BidQuote, 'amount' | 'fx_rate' | 'exclusions'>): number {
  return asQuotedCents(q) + plugCents(q.exclusions);
}

export function rowValueCents(row: BidRow): number {
  const chosen = row.quotes.find((q) => q.id === row.chosen_quote_id);
  return chosen ? adjustedCents(chosen) : toCents(row.plug_amount);
}

function pct(c: number, p: string): number {
  return Math.round((c * Number(p || '0')) / 100);
}

export function computeTotals(board: Board): Totals {
  const direct = board.rows.reduce((a, r) => a + rowValueCents(r), 0);
  const estimate = board.rows.reduce((a, r) => a + toCents(r.plug_amount), 0);
  const overhead = pct(direct, board.overhead_pct);
  const risk = pct(direct, board.risk_pct);
  const profit = pct(direct + overhead + risk, board.profit_pct);
  const total = direct + overhead + risk + profit;
  let estTotal = estimate + pct(estimate, board.overhead_pct) + pct(estimate, board.risk_pct);
  estTotal += pct(estTotal, board.profit_pct);
  const last = board.totals.last_snapshot_total;
  return {
    direct: fromCents(direct),
    overhead: fromCents(overhead),
    risk: fromCents(risk),
    profit: fromCents(profit),
    markup: fromCents(overhead + risk + profit),
    bid_total: fromCents(total),
    estimate_direct: fromCents(estimate),
    estimate_total: fromCents(estTotal),
    vs_estimate: fromCents(direct - estimate),
    last_snapshot_total: last,
    delta_vs_snapshot: last === null ? null : fromCents(total - toCents(last)),
  };
}

/** Rebuild the derived figures of a locally edited board. */
export function recompute(board: Board): Board {
  const rows = board.rows.map((r) => {
    const quotes = r.quotes.map((q) => ({
      ...q,
      as_quoted: fromCents(asQuotedCents(q)),
      adjusted: fromCents(adjustedCents(q)),
      open_exclusions: q.exclusions.filter((x) => x.status === 'open').length,
      is_chosen: q.id === r.chosen_quote_id,
    }));
    const next = { ...r, quotes };
    const value = rowValueCents(next);
    return { ...next, value: fromCents(value), delta_vs_plug: fromCents(value - toCents(r.plug_amount)) };
  });
  const next = { ...board, rows };
  return { ...next, totals: computeTotals(next) };
}

/** Figures that changed between two versions of the board, keyed by cell id, in cents. */
export function changedCells(prev: Board | undefined, next: Board): Map<string, number> {
  const out = new Map<string, number>();
  if (!prev) return out;
  const before = new Map<string, string>();
  for (const r of prev.rows) {
    before.set(`row:${r.id}`, r.value);
    for (const q of r.quotes) before.set(`quote:${q.id}`, q.adjusted);
  }
  before.set('total', prev.totals.bid_total);
  const check = (key: string, value: string) => {
    const old = before.get(key);
    if (old !== undefined && old !== value) out.set(key, toCents(value) - toCents(old));
  };
  for (const r of next.rows) {
    check(`row:${r.id}`, r.value);
    for (const q of r.quotes) check(`quote:${q.id}`, q.adjusted);
  }
  check('total', next.totals.bid_total);
  return out;
}

export interface Countdown {
  overdue: boolean;
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
  totalMs: number;
}

/** Time left to a deadline string; ``null`` when the tender has none or it does not parse. */
export function countdown(deadline: string | null, now: number): Countdown | null {
  if (!deadline) return null;
  const at = Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(deadline) ? `${deadline}T23:59:59` : deadline);
  if (Number.isNaN(at)) return null;
  const diff = at - now;
  const abs = Math.abs(diff);
  return {
    overdue: diff < 0,
    days: Math.floor(abs / 86_400_000),
    hours: Math.floor((abs % 86_400_000) / 3_600_000),
    minutes: Math.floor((abs % 3_600_000) / 60_000),
    seconds: Math.floor((abs % 60_000) / 1000),
    totalMs: diff,
  };
}
