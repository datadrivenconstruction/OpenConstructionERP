// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** The fixed-point, locale-neutral decimal spelling emitted by money APIs. */
export function isDecimalString(value: string): boolean {
  return value.trim() === value && /^-?\d+(?:\.\d+)?$/.test(value);
}

/** Subtract wire decimals without rounding; invalid values remain unavailable. */
export function subtractDecimalStrings(left: string, right: string): string | null {
  if (!isDecimalString(left) || !isDecimalString(right)) return null;
  const leftScale = left.split('.')[1]?.length ?? 0;
  const rightScale = right.split('.')[1]?.length ?? 0;
  const scale = Math.max(leftScale, rightScale);
  const a = BigInt(left.replace('.', '')) * 10n ** BigInt(scale - leftScale);
  const b = BigInt(right.replace('.', '')) * 10n ** BigInt(scale - rightScale);
  const result = a - b;
  const digits = (result < 0n ? -result : result).toString().padStart(scale + 1, '0');
  const magnitude = scale ? `${digits.slice(0, -scale)}.${digits.slice(-scale)}` : digits;
  return `${result < 0n ? '-' : ''}${magnitude}`;
}

function toScaled(value: string, scale: number): bigint {
  const own = value.split('.')[1]?.length ?? 0;
  return BigInt(value.replace('.', '')) * 10n ** BigInt(scale - own);
}

function fromScaled(result: bigint, scale: number): string {
  const digits = (result < 0n ? -result : result).toString().padStart(scale + 1, '0');
  const magnitude = scale ? `${digits.slice(0, -scale)}.${digits.slice(-scale)}` : digits;
  return `${result < 0n ? '-' : ''}${magnitude}`;
}

/** Add wire decimals without rounding; invalid values remain unavailable. */
export function addDecimalStrings(left: string, right: string): string | null {
  return sumDecimalStrings([left, right]);
}

/**
 * Sum wire decimals exactly, at the widest scale of the operands. An empty list
 * sums to "0". Any invalid operand makes the whole sum unavailable (null), so a
 * total never silently drops a figure it could not read.
 */
export function sumDecimalStrings(values: readonly string[]): string | null {
  if (values.length === 0) return '0';
  if (!values.every(isDecimalString)) return null;
  const scale = Math.max(...values.map((v) => v.split('.')[1]?.length ?? 0));
  let total = 0n;
  for (const v of values) total += toScaled(v, scale);
  return fromScaled(total, scale);
}

/** Sum money strings for display: unreadable or missing figures count as zero. */
export function sumMoneyStrings(values: readonly (string | null | undefined)[]): string {
  const clean = values.map((v) => (typeof v === 'string' && isDecimalString(v) ? v : '0'));
  return sumDecimalStrings(clean) ?? '0';
}

/**
 * Mean of `value` weighted by `weight`, computed exactly and rounded half up to
 * `digits` decimals (trailing zeros trimmed). Null when there is nothing to
 * average (no entries, a non-positive total weight) or any operand is not a
 * plain decimal.
 */
export function weightedMeanDecimalStrings(
  entries: readonly { weight: string; value: string }[],
  digits = 6,
): string | null {
  if (entries.length === 0) return null;
  if (!entries.every((e) => isDecimalString(e.weight) && isDecimalString(e.value))) return null;
  const wScale = Math.max(...entries.map((e) => e.weight.split('.')[1]?.length ?? 0));
  const vScale = Math.max(...entries.map((e) => e.value.split('.')[1]?.length ?? 0));
  let weighted = 0n;
  let total = 0n;
  for (const e of entries) {
    const w = toScaled(e.weight, wScale);
    weighted += w * toScaled(e.value, vScale);
    total += w;
  }
  if (total <= 0n) return null;
  // weighted / total is scaled by 10^vScale; bring it to `digits` and round half up.
  const target = 10n ** BigInt(digits);
  const numerator = weighted * target;
  const denominator = total * 10n ** BigInt(vScale);
  const negative = numerator < 0n;
  const abs = negative ? -numerator : numerator;
  let q = abs / denominator;
  if ((abs % denominator) * 2n >= denominator) q += 1n;
  const text = fromScaled(negative ? -q : q, digits);
  return text.includes('.') ? text.replace(/\.?0+$/, '') : text;
}
