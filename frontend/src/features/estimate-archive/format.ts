// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sealed figures arrive as exact decimal strings; these write them with the
 * reader's separators without dropping a sealed digit.
 */
import { fmtNumber, fmtPercent } from '@/shared/lib/formatters';

type Raw = string | number | null | undefined;

const blank = (v: Raw) => v == null || (typeof v === 'string' && v.trim() === '');

/** Fraction digits the value itself carries, so 0.025 keeps three. */
function digitsOf(v: Raw): number {
  const s = String(v ?? '');
  const dot = s.indexOf('.');
  return dot < 0 ? 0 : Math.min(s.length - dot - 1, 6);
}

/** A consumption or quantity, with exactly the digits it was sealed with. */
export function fmtDecimal(v: Raw): string {
  return blank(v) ? '' : fmtNumber(v, digitsOf(v));
}

/** A unit cost, net or rate: two decimals. */
export function fmtRate(v: Raw): string {
  return blank(v) ? '' : fmtNumber(v, 2);
}

/** A markup step percentage on the 0-100 scale. */
export function fmtStepPercent(v: Raw): string {
  return blank(v) ? '' : fmtPercent(v, digitsOf(v));
}
