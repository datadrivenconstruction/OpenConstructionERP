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
