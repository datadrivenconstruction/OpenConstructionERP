// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers for the quantity check view: the filters, the highlight band
 * and the totals of the rows on screen.
 *
 * The server decides over, under and not measured exactly. The highlight band
 * is the viewer's own setting and means nothing more than "show me what moved
 * more than this": no contractual consequence is read into it here.
 */
import type { QuantityCheckLine } from './api';

export type QuantityFilter = 'all' | 'over' | 'under' | 'not_measured' | 'beyond';

/** The band a fresh viewer starts with, in percent. Adjustable on screen. */
export const DEFAULT_THRESHOLD_PCT = 10;

/** Decimal string to a finite number, or NaN when the figure is absent. */
export function num(value: string | null | undefined): number {
  if (value === null || value === undefined || value === '') return Number.NaN;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

/**
 * Whether a measured line moved further from its contract quantity than the band.
 *
 * A line with no ratio (contract quantity zero, or added since the baseline)
 * that measured anything at all is beyond any band: all of it is outside the
 * contract.
 */
export function isBeyondThreshold(line: QuantityCheckLine, thresholdPct: number): boolean {
  if (line.status === 'not_measured') return false;
  const diff = num(line.difference);
  if (Number.isNaN(diff) || diff === 0) return false;
  const pct = num(line.difference_pct);
  if (Number.isNaN(pct)) return true;
  return Math.abs(pct) > thresholdPct;
}

export function filterLines(
  lines: QuantityCheckLine[],
  filter: QuantityFilter,
  thresholdPct: number,
): QuantityCheckLine[] {
  switch (filter) {
    case 'over':
      return lines.filter((l) => l.status === 'over');
    case 'under':
      return lines.filter((l) => l.status === 'under');
    case 'not_measured':
      return lines.filter((l) => l.status === 'not_measured');
    case 'beyond':
      return lines.filter((l) => isBeyondThreshold(l, thresholdPct));
    default:
      return lines;
  }
}

export interface ShownTotals {
  count: number;
  contractValue: number;
  over: number;
  under: number;
  net: number;
}

/**
 * Totals of the rows shown. Over and under are kept apart as well as netted,
 * so an overrun of 50k and a shortfall of 50k do not read as nothing.
 */
export function totalsOf(lines: QuantityCheckLine[]): ShownTotals {
  const out: ShownTotals = { count: lines.length, contractValue: 0, over: 0, under: 0, net: 0 };
  for (const line of lines) {
    const value = num(line.contract_value);
    if (!Number.isNaN(value)) out.contractValue += value;
    const cost = num(line.cost_effect);
    if (Number.isNaN(cost)) continue;
    if (cost > 0) out.over += cost;
    else out.under += cost;
    out.net += cost;
  }
  // Rounded to the cent here, once, so a column of cents does not show a
  // float tail through the formatter.
  out.contractValue = Math.round(out.contractValue * 100) / 100;
  out.over = Math.round(out.over * 100) / 100;
  out.under = Math.round(out.under * 100) / 100;
  out.net = Math.round(out.net * 100) / 100;
  return out;
}

/** Read the viewer's band, falling back to the default on any storage trouble. */
export function readThreshold(storageKey: string): number {
  try {
    const raw = window.localStorage.getItem(storageKey);
    const parsed = raw === null ? Number.NaN : Number(raw);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : DEFAULT_THRESHOLD_PCT;
  } catch {
    return DEFAULT_THRESHOLD_PCT;
  }
}

export function writeThreshold(storageKey: string, value: number): void {
  try {
    window.localStorage.setItem(storageKey, String(value));
  } catch {
    // A private window or blocked storage: the band still applies this session.
  }
}
