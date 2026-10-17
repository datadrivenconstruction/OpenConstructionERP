// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Exact arithmetic behind the cost allocation drawer.
//
// Shares are typed by a person and compared with 100 (percent) or with the
// position quantity (quantity), with the same relative tolerance the backend
// applies (0.01 %). Everything runs on decimal strings scaled into BigInt, so
// 33.333 + 33.333 + 33.334 is exactly 100 here, as it is on the server.

import { normalizeDecimalSeparators } from '@/shared/lib/parseDecimal';

/** Relative tolerance of a share total against its target: 0.01 %. */
export const SHARE_TOLERANCE = '0.0001';

/** Most decimals a share may carry; the backend refuses more (`decimal_places=6`). */
export const MAX_SHARE_DECIMALS = 6;

/** Most shares one position may be split into; the backend refuses more. */
export const MAX_SHARES = 50;

const DECIMAL_RE = /^([+-])?(\d+)(?:\.(\d*))?$|^([+-])?\.(\d+)$/;

interface Scaled {
  n: bigint;
  scale: number;
}

/** A decimal string as a scaled integer, or null when it is not a plain decimal. */
export function parseScaled(raw: string): Scaled | null {
  const m = DECIMAL_RE.exec(raw.trim());
  if (!m) return null;
  const sign = m[1] ?? m[4] ?? '';
  const whole = m[2] ?? '0';
  const frac = m[3] ?? m[5] ?? '';
  const n = BigInt(`${whole}${frac}` || '0');
  return { n: sign === '-' ? -n : n, scale: frac.length };
}

function rescale(v: Scaled, scale: number): bigint {
  return v.n * 10n ** BigInt(scale - v.scale);
}

function format(n: bigint, scale: number): string {
  const negative = n < 0n;
  const digits = (negative ? -n : n).toString().padStart(scale + 1, '0');
  const whole = scale > 0 ? digits.slice(0, -scale) : digits;
  let frac = scale > 0 ? digits.slice(-scale) : '';
  frac = frac.replace(/0+$/, '');
  const body = frac ? `${whole}.${frac}` : whole;
  return negative && body !== '0' ? `-${body}` : body;
}

/** Normalise what a person typed ("12,5", " 40 ") into a decimal string, or null. */
export function normalizeShare(raw: string): string | null {
  const text = normalizeDecimalSeparators(raw.trim());
  if (!text) return null;
  return parseScaled(text) ? text : null;
}

export interface ShareCheck {
  /** Sum of the shares, a decimal string. */
  total: string;
  /** 100 for percent, the position quantity for quantity. */
  expected: string;
  /** expected - total, a decimal string (what is left to place). */
  remaining: string;
  /** Every share parsed and is greater than zero. */
  sharesValid: boolean;
  /** Some share carries more than {@link MAX_SHARE_DECIMALS} decimals. */
  tooPrecise: boolean;
  /** The total meets the target within the tolerance. */
  addsUp: boolean;
}

/**
 * Compare typed shares with their target.
 *
 * `addsUp` follows the backend rule: |total - expected| <= |expected| * 0.0001.
 * A quantity split of a position without quantity never adds up.
 */
export function checkShares(mode: 'percent' | 'quantity', shares: readonly string[], quantity: string): ShareCheck {
  const expectedRaw = mode === 'percent' ? '100' : quantity || '0';
  const parsed = shares.map((s) => {
    const text = normalizeShare(s);
    return text ? parseScaled(text) : null;
  });
  const expected = parseScaled(expectedRaw) ?? { n: 0n, scale: 0 };
  const tol = parseScaled(SHARE_TOLERANCE)!;
  const sharesValid = parsed.length > 0 && parsed.every((p) => p !== null && p.n > 0n);
  const scale = Math.max(expected.scale, tol.scale, ...parsed.map((p) => p?.scale ?? 0));
  let total = 0n;
  for (const p of parsed) if (p) total += rescale(p, scale);
  const exp = rescale(expected, scale);
  const diff = exp - total;
  // |diff| <= |expected| * tolerance, both sides at scale + tol.scale.
  const absDiff = (diff < 0n ? -diff : diff) * 10n ** BigInt(tol.scale);
  const allowed = (exp < 0n ? -exp : exp) * tol.n;
  return {
    total: format(total, scale),
    expected: format(exp, scale),
    remaining: format(diff, scale),
    sharesValid,
    tooPrecise: parsed.some((p) => p !== null && p.scale > MAX_SHARE_DECIMALS),
    addsUp: sharesValid && exp !== 0n && absDiff <= allowed,
  };
}

/**
 * Split an amount by share weights to the cent, the parts adding up exactly.
 *
 * Each part gets its floor of cents; the cents left over go one each to the
 * parts with the largest remainders, the first part winning a tie. A credit
 * keeps its sign. Shares that do not parse weigh nothing.
 */
export function splitPreview(amount: string, shares: readonly string[]): string[] {
  const total = parseScaled(amount);
  const weights = shares.map((s) => {
    const text = normalizeShare(s);
    const p = text ? parseScaled(text) : null;
    return p && p.n > 0n ? p : null;
  });
  if (!total || weights.every((w) => w === null)) return shares.map(() => '0');
  const scale = Math.max(0, ...weights.map((w) => w?.scale ?? 0));
  const w = weights.map((p) => (p ? rescale(p, scale) : 0n));
  const sumW = w.reduce((a, b) => a + b, 0n);
  // Cents, rounded half away from zero.
  const centsScaled = rescale(total, Math.max(total.scale, 2));
  const divisor = 10n ** BigInt(Math.max(total.scale, 2) - 2);
  const negative = centsScaled < 0n;
  const absScaled = negative ? -centsScaled : centsScaled;
  const cents = (absScaled + divisor / 2n) / divisor;
  const floors = w.map((x) => (cents * x) / sumW);
  const rems = w.map((x, i) => cents * x - floors[i]! * sumW);
  let left = cents - floors.reduce((a, b) => a + b, 0n);
  const order = rems
    .map((r, i) => ({ r, i }))
    .filter(({ i }) => w[i]! > 0n)
    .sort((a, b) => (a.r === b.r ? a.i - b.i : a.r > b.r ? -1 : 1));
  for (const { i } of order) {
    if (left <= 0n) break;
    floors[i] = floors[i]! + 1n;
    left -= 1n;
  }
  return floors.map((c) => format(negative ? -c : c, 2));
}
