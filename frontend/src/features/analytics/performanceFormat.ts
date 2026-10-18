// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Display helpers shared by the Performance tab and the estimating screens that
// show a historical range. Pure, so every screen formats a benchmark the same way.

import { fmtNumber, fmtPercent } from '@/shared/lib/formatters';
import { toNumber, type Decimalish } from './performance';

/** Up to four significant decimals: productivity ratios are small numbers. */
export function fmtValue(value: Decimalish | undefined): string | null {
  const n = toNumber(value);
  if (n === null) return null;
  return fmtNumber(n, Math.abs(n) >= 100 ? 0 : Math.abs(n) >= 1 ? 2 : 4);
}

/** A unit as an estimator writes it: m2 -> m², m3 -> m³, also inside h/m2. */
export function prettyUnit(unit: string | null | undefined): string {
  return (unit ?? '')
    .split('/')
    .map((part) => part.replace(/(^|[a-z])2$/i, '$1²').replace(/(^|[a-z])3$/i, '$1³'))
    .join('/');
}

/** A share such as 0.25 as a signed percentage, "+25 %"; null when there is none. */
export function fmtVariance(value: Decimalish | undefined): string | null {
  const n = toNumber(value);
  if (n === null) return null;
  return `${n > 0 ? '+' : ''}${fmtPercent(n * 100)}`;
}

/** A 0..1 share as a percentage; null when the whole was zero. */
export function fmtShare(value: Decimalish | undefined): string | null {
  const n = toNumber(value);
  return n === null ? null : fmtPercent(n * 100);
}
