// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Exact decimal sums for the share matrix, so the "adds up" mark next to a line never
 * disagrees with the server by a float digit. Money splits are computed on the server only.
 */

const SCALE = 4;
const FACTOR = 10n ** BigInt(SCALE);

/** A decimal string as an integer of 1/10,000 units; null for empty or unreadable text. */
export function toUnits(value: string | null | undefined): bigint | null {
  if (value == null) return null;
  const text = String(value).trim().replace(/[\s_]/g, '').replace(',', '.');
  if (!/^-?\d*(\.\d*)?$/.test(text) || text === '' || text === '.' || text === '-') return null;
  const negative = text.startsWith('-');
  const [whole = '', frac = ''] = text.replace('-', '').split('.');
  if (frac.length > SCALE) return null;
  const units = BigInt(whole || '0') * FACTOR + BigInt((frac + '0'.repeat(SCALE)).slice(0, SCALE));
  return negative ? -units : units;
}

/** Units back to a plain decimal string without trailing zeros. */
export function fromUnits(units: bigint): string {
  const negative = units < 0n;
  const abs = negative ? -units : units;
  const whole = abs / FACTOR;
  const frac = (abs % FACTOR).toString().padStart(SCALE, '0').replace(/0+$/, '');
  return `${negative ? '-' : ''}${whole}${frac ? `.${frac}` : ''}`;
}

export interface ShareCheck {
  /** Sum of the shares typed so far. */
  sum: string;
  /** Line quantity minus the sum; positive means some of the line is still unassigned. */
  remaining: string;
  /** Number of projects with no share entered (blank, not zero). */
  blanks: number;
  ok: boolean;
}

/** Whether the shares of one line cover its quantity exactly, with every project answered. */
export function checkShares(quantity: string, shares: (string | null | undefined)[]): ShareCheck {
  let sum = 0n;
  let blanks = 0;
  for (const share of shares) {
    const units = toUnits(share);
    if (units == null) blanks += 1;
    else sum += units;
  }
  const remaining = (toUnits(quantity) ?? 0n) - sum;
  return { sum: fromUnits(sum), remaining: fromUnits(remaining), blanks, ok: blanks === 0 && remaining === 0n };
}

/** Split a line evenly in whole units, the remainder going to the first projects. */
export function evenShares(quantity: string, parts: number): string[] {
  const total = toUnits(quantity);
  if (total == null || parts <= 0) return [];
  const wholeUnits = total / FACTOR;
  const base = wholeUnits / BigInt(parts);
  let rest = wholeUnits - base * BigInt(parts);
  const fraction = total - wholeUnits * FACTOR;
  return Array.from({ length: parts }, (_, i) => {
    let units = base * FACTOR;
    if (rest > 0n) {
      units += FACTOR;
      rest -= 1n;
    }
    if (i === parts - 1) units += fraction;
    return fromUnits(units);
  });
}
