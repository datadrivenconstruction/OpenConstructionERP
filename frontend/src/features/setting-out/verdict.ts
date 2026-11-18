// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The instant verdict a phone card shows while values are typed. Mirrors the
 * backend's `stakeout_math.stake_delta` (the saved record is the authority):
 * d = sqrt(dE^2 + dN^2) and dZ in mm, rounded to 0.1 mm; pass when
 * d <= horizontal tolerance and |dZ| <= vertical tolerance.
 */

import type { Verdict } from './api';
import { fmtFixed } from '@/shared/lib/formatters';

export interface InstantDelta {
  d_mm: number;
  dz_mm: number | null;
  verdict: Verdict;
}

const mm = (m: number) => Math.round(m * 10000) / 10;

/** Parse a typed decimal; accepts a decimal comma; null for blank or junk. */
export function parseDecimal(text: string): number | null {
  const s = text.trim().replace(/\s/g, '').replace(',', '.');
  if (!s || !/^[-+]?\d*\.?\d+$/.test(s)) return null;
  return Number(s);
}

export function instantDelta(
  design: { e: number; n: number; z: number | null },
  measured: { e: number; n: number; z: number | null },
  tolH: number | null,
  tolV: number | null,
): InstantDelta {
  const d = mm(Math.hypot(measured.e - design.e, measured.n - design.n));
  const dz = design.z != null && measured.z != null ? mm(measured.z - design.z) : null;
  if (tolH == null) return { d_mm: d, dz_mm: dz, verdict: 'no_tolerance' };
  let ok = d <= tolH;
  if (ok && tolV != null && dz != null) ok = Math.abs(dz) <= tolV;
  return { d_mm: d, dz_mm: dz, verdict: ok ? 'pass' : 'fail' };
}

/** "5" for whole millimetres, "4.6" otherwise. */
export const fmtMm = (v: number | null | undefined) => (v == null ? '' : Number.isInteger(v) ? String(v) : fmtFixed(v, 1));
export const fmtCoord = (v: number | null | undefined) => (v == null ? '' : fmtFixed(v, 3));
