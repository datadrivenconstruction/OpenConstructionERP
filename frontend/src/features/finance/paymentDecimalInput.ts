// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Exact ASCII number-input spelling, bounded by the payment request's 50 chars. */
export function paymentDecimalInput(raw: string): string | null {
  const input = raw.trim();
  if (input === '') return '0';
  if (input.length > 50) return null;
  const match = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(input);
  if (!match) return null;
  const integer = match[2] ?? '0';
  const fraction = match[3] ?? match[4] ?? '';
  const digits = integer + fraction;
  // Zero does not need exponent-sized padding, even for an enormous exponent.
  if (!/[1-9]/.test(digits)) return '0';
  const point = BigInt(integer.length) + BigInt(match[5] ?? '0');
  const count = BigInt(digits.length);
  const sign = match[1] === '-' ? '-' : '';
  const length = point <= 0n ? 2n - point + count : point >= count ? point : count + 1n;
  if (length + BigInt(sign.length) > 50n) return null;
  // Only the bounded decimal-point index becomes a number, never the amount.
  const position = Number(point);
  const fixed = position <= 0 ? `0.${'0'.repeat(-position)}${digits}`
    : position >= digits.length ? digits + '0'.repeat(position - digits.length)
      : `${digits.slice(0, position)}.${digits.slice(position)}`;
  return sign + fixed.replace(/^0+(?=\d)/, '');
}

/** Preserve retry identity; only overlength keys need deterministic SHA-256. */
export async function paymentIdempotencyKey(original: string): Promise<string> {
  if (original.length <= 64) return original;
  if (!globalThis.crypto?.subtle) throw new Error('Key generation unavailable');
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(original));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}
