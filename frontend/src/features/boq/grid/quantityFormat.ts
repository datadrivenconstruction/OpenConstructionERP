/**
 * How many decimals the BOQ grid shows for a quantity.
 *
 * Three, fixed, so the decimal marks line up down the column and a measured
 * 2.625 m3 is shown as priced (line totals use the full value). Counted units
 * (pieces, each, Stk, шт ...) holding a whole number show none: "12 pcs", not
 * "12.000 pcs". Values below 0.001 keep their significant digits.
 */
const COUNT_UNITS = new Set([
  'pcs', 'pc', 'piece', 'pieces', 'nr', 'no', 'ea', 'each', 'st', 'stk', 'stck', 'stück', 'pce', 'u', 'un',
  'unit', 'units', 'item', 'items', 'set', 'sets', 'шт', 'шт.', 'ед', 'ens', 'u.', 'pz', 'szt', 'ks',
]);

export function isCountUnit(unit: string | null | undefined): boolean {
  return COUNT_UNITS.has((unit ?? '').trim().toLowerCase().replace(/\.$/, ''));
}

export function quantityFractionDigits(value: number, unit: string | null | undefined): { min: number; max: number } {
  const abs = Math.abs(value);
  if (isCountUnit(unit) && Number.isInteger(value)) return { min: 0, max: 0 };
  if (abs > 0 && abs < 0.001) return { min: 3, max: Math.max(6, Math.ceil(-Math.log10(abs)) + 2) };
  return { min: 3, max: 3 };
}
