/**
 * Payment schedule arithmetic for the customer offer. Percent and amount are decimal strings on the
 * wire and stay strings here; every sum is exact BigInt arithmetic scaled by 10^6, never a float.
 */

const SCALE = 6;
const ONE = 10n ** BigInt(SCALE);

export interface ScheduleRow {
  code: string;
  name: string;
  kind: 'deposit' | 'progress' | 'final';
  percent: string;
  /** Net amount of the instalment. */
  value: string;
  due: { type: string; [key: string]: unknown };
  lag_days: number;
}

export type BarState = 'ok' | 'left' | 'over';

export interface ScheduleBar {
  state: BarState;
  percent: string;
  /** Net amount still to schedule (state left) or scheduled beyond the net (state over); zero when ok. */
  amount: string;
}

/** Parse a decimal string to a scaled integer; anything unparseable is zero. */
export function toUnits(text: string | null | undefined): bigint {
  const m = /^\s*(-?)(\d*)(?:[.,](\d*))?\s*$/.exec(text ?? '');
  if (!m || (m[2] === '' && !m[3])) return 0n;
  const frac = ((m[3] ?? '') + '0'.repeat(SCALE)).slice(0, SCALE);
  const units = BigInt(m[2] || '0') * ONE + BigInt(frac || '0');
  return m[1] === '-' ? -units : units;
}

/** Format scaled units with `places` decimals, rounding half away from zero. */
export function fromUnits(units: bigint, places: number): string {
  const negative = units < 0n;
  const abs = negative ? -units : units;
  const drop = 10n ** BigInt(SCALE - places);
  const rounded = (abs + drop / 2n) / drop;
  const text = rounded.toString().padStart(places + 1, '0');
  const body = places > 0 ? `${text.slice(0, -places)}.${text.slice(-places)}` : text;
  return negative && rounded !== 0n ? `-${body}` : body;
}

export function minorDigits(currency: string): number {
  if (/^(JPY|KRW|VND|CLP|ISK|UGX|PYG|XAF|XOF|XPF|RWF|KMF|DJF|GNF|VUV)$/.test(currency)) return 0;
  if (/^(BHD|IQD|JOD|KWD|LYD|OMR|TND)$/.test(currency)) return 3;
  return 2;
}

function mulDiv(a: bigint, b: bigint, d: bigint): bigint {
  return d === 0n ? 0n : (a * b) / d;
}

/** Amount of `percent` of `net`, in scaled units. */
export function amountOf(net: string, percent: string, places: number): string {
  return fromUnits(mulDiv(toUnits(net), toUnits(percent), 100n * ONE), places);
}

/** Percent that `amount` is of `net`, four decimals. */
export function percentOf(net: string, amount: string): string {
  const n = toUnits(net);
  return n === 0n ? '0.0000' : fromUnits(mulDiv(toUnits(amount), 100n * ONE, n), 4);
}

/**
 * Re-derive the other half of an edited row, then let the last row take the rest so the net is met
 * exactly. `edited` names the field the user typed: 'percent' recomputes the amount, 'value' the percent.
 */
export function syncRows(
  rows: ScheduleRow[],
  net: string,
  currency: string,
  edited?: { index: number; field: 'percent' | 'value' },
): ScheduleRow[] {
  const places = minorDigits(currency);
  const out = rows.map((r) => ({ ...r }));
  const row = edited ? out[edited.index] : undefined;
  if (edited && row) {
    if (edited.field === 'percent') row.value = amountOf(net, row.percent, places);
    else row.percent = percentOf(net, row.value);
  }
  return takeTheRest(out, net, places);
}

/** The last row absorbs rounding: its amount is the net minus the rows above it. */
export function takeTheRest(rows: ScheduleRow[], net: string, places: number): ScheduleRow[] {
  if (rows.length === 0) return rows;
  const last = rows.length - 1;
  let paid = 0n;
  for (let i = 0; i < last; i += 1) paid += toUnits(rows[i]?.value);
  const rest = toUnits(net) - paid;
  const row: ScheduleRow = { ...(rows[last] as ScheduleRow), value: fromUnits(rest, places) };
  row.percent = percentOf(net, row.value);
  return [...rows.slice(0, last), row];
}

/** The running bar under the table: how much of the net is scheduled. */
export function scheduleBar(rows: ScheduleRow[], net: string, currency: string): ScheduleBar {
  const places = minorDigits(currency);
  const netUnits = toUnits(net);
  const scheduled = rows.reduce((sum, r) => sum + toUnits(r.value), 0n);
  const percent = netUnits === 0n ? 0n : mulDiv(scheduled, 100n * ONE, netUnits);
  const diff = scheduled - netUnits;
  const roundedPct = fromUnits(percent, 2);
  if (fromUnits(diff, places) === fromUnits(0n, places)) return { state: 'ok', percent: roundedPct, amount: fromUnits(0n, places) };
  if (diff < 0n) return { state: 'left', percent: roundedPct, amount: fromUnits(-diff, places) };
  return { state: 'over', percent: roundedPct, amount: fromUnits(diff, places) };
}

/** The standard splits offered in the template menu. */
export const SCHEDULE_TEMPLATES: Record<string, { name: string; kind: ScheduleRow['kind']; percent: string; due: string }[]> = {
  '30_40_30': [
    { name: 'Deposit', kind: 'deposit', percent: '30', due: 'signing' },
    { name: 'Progress', kind: 'progress', percent: '40', due: 'date' },
    { name: 'Final', kind: 'final', percent: '30', due: 'acceptance' },
  ],
  '50_50': [
    { name: 'Deposit', kind: 'deposit', percent: '50', due: 'signing' },
    { name: 'Final', kind: 'final', percent: '50', due: 'acceptance' },
  ],
  completion: [{ name: 'Final', kind: 'final', percent: '100', due: 'acceptance' }],
};

export function rowsFromTemplate(key: string, net: string, currency: string): ScheduleRow[] {
  const spec = SCHEDULE_TEMPLATES[key] ?? [];
  const places = minorDigits(currency);
  const rows: ScheduleRow[] = spec.map((s, i) => ({
    code: String(i + 1),
    name: s.name,
    kind: s.kind,
    percent: s.percent,
    value: amountOf(net, s.percent, places),
    due: { type: s.due },
    lag_days: 0,
  }));
  return takeTheRest(rows, net, places);
}
