// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Angle and coordinate helpers of the survey calculations. The server parses
 * angles too; these only check input as it is typed and format results.
 */

export type AngleUnit = 'deg' | 'dms' | 'gon';
export const ANGLE_UNITS: AngleUnit[] = ['dms', 'deg', 'gon'];

/** Degrees from text in ``unit``: "49 06 23.4", "49°06'23.4\"", "49-06-23.4", "49.1065" or gon. Null when unreadable. */
export function parseAngle(text: string, unit: AngleUnit): number | null {
  const s = text.trim().replace(',', '.');
  if (!s) return null;
  const negative = s.startsWith('-');
  const body = negative ? s.slice(1) : s;
  if (unit === 'dms') {
    const parts = body.split(/[^0-9.]+/).filter(Boolean).map(Number);
    if (parts.length === 0 || parts.length > 3 || parts.some((p) => !Number.isFinite(p))) return null;
    const [d, m = 0, sec = 0] = parts;
    if (parts.length > 1 && (m >= 60 || sec >= 60)) return null;
    const value = d + m / 60 + sec / 3600;
    return negative ? -value : value;
  }
  if (!/^\d*\.?\d+$|^\d+\.$/.test(body)) return null;
  const value = Number(body) * (unit === 'gon' ? 0.9 : 1);
  return negative ? -value : value;
}

/** ``deg`` in ``unit`` as text: DMS to 0.1", decimal degrees to 6 places, gon to 5. */
export function formatAngle(deg: number | null | undefined, unit: AngleUnit): string {
  if (deg == null || !Number.isFinite(deg)) return '';
  if (unit === 'gon') return (deg / 0.9).toFixed(5);
  if (unit === 'deg') return deg.toFixed(6);
  const sign = deg < 0 ? '-' : '';
  let tenths = Math.round(Math.abs(deg) * 36000);
  const d = Math.floor(tenths / 36000);
  tenths -= d * 36000;
  const m = Math.floor(tenths / 600);
  const s = (tenths - m * 600) / 10;
  return `${sign}${d}°${String(m).padStart(2, '0')}'${s.toFixed(1).padStart(4, '0')}"`;
}

/** "E N" or "E N Z" (space, tab, comma or semicolon separated). */
export function parseCoord(text: string): number[] | null {
  const parts = text.trim().split(/[\s;,]+/).filter(Boolean).map(Number);
  if (parts.length < 2 || parts.length > 3 || parts.some((p) => !Number.isFinite(p))) return null;
  return parts;
}

/** One coordinate pair per line. */
export function parseRing(text: string): number[][] | null {
  const rows = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const out = rows.map(parseCoord);
  return out.length >= 3 && out.every(Boolean) ? (out as number[][]).map((p) => p.slice(0, 2)) : null;
}

/** Fixed decimals for metres; empty for null. */
export function fmtM(value: number | null | undefined, places = 3): string {
  return value == null || !Number.isFinite(value) ? '' : value.toFixed(places);
}
