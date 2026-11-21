// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Angles and directions. Internally every angle is decimal degrees and every
 * direction is a grid azimuth, clockwise from grid north, in [0, 360).
 *
 * The parser reads what surveyors type: 12°34'56", 12 34 56, 12-34-56,
 * 12:34:56, 12.3456 (in the project unit), 12.3456g / 12.3456 gon, 12.3456°,
 * and quadrant bearings N45°30'E / S 12 30 W.
 */

import type { AngleUnit, PlanConventions } from './conventions';
import { fmtFixed } from '@/shared/lib/formatters';

const GON = 0.9;

export function normalizeAzimuth(deg: number): number {
  const r = deg % 360;
  return r < 0 ? r + 360 : r === 360 ? 0 : r;
}

function num(s: string): number {
  return Number(s.replace(',', '.'));
}

/** Degrees from text; a unit marker in the text wins over `unit`. Null when unreadable. */
export function parseAngle(text: string, unit: AngleUnit): number | null {
  let s = text.trim();
  if (!s) return null;
  let negative = false;
  if (s.startsWith('-') || s.startsWith('−')) {
    negative = true;
    s = s.slice(1).trim();
  } else if (s.startsWith('+')) {
    s = s.slice(1).trim();
  }
  let value: number | null = null;
  const gon = /^(\d+(?:[.,]\d*)?|[.,]\d+)\s*(?:g|gon|grad|gr|ᵍ)$/i.exec(s);
  const deg = /^(\d+(?:[.,]\d*)?|[.,]\d+)\s*(?:°|d|deg)$/i.exec(s);
  if (gon) value = num(gon[1]!) * GON;
  else if (deg) value = num(deg[1]!);
  else {
    const hasDmsMark = /['′"″°]/.test(s);
    const parts = s
      .replace(/["″]\s*$/, '')
      .split(/\s*(?:°|['′]|["″]|:|-|\s)\s*/)
      .filter(Boolean);
    if (parts.length === 0 || parts.length > 3 || parts.some((p) => !/^(\d+(?:[.,]\d*)?|[.,]\d+)$/.test(p))) return null;
    if (parts.length === 1 && !hasDmsMark) {
      const v = num(parts[0]!);
      value = unit === 'gon' ? v * GON : v;
    } else {
      // More than one part is always D M S, whatever the project unit.
      const [d, m = '0', sec = '0'] = parts;
      const mm = num(m);
      const ss = num(sec);
      if (mm >= 60 || ss >= 60) return null;
      if (parts.length > 1 && /[.,]/.test(d!)) return null;
      value = num(d!) + mm / 60 + ss / 3600;
    }
  }
  if (value == null || !Number.isFinite(value)) return null;
  return negative ? -value : value;
}

/** Text of `deg` in `unit`: DMS 12°34'56.0", deg 12.345678°, gon 13.71734 gon. */
export function formatAngle(deg: number | null | undefined, unit: AngleUnit, decimals: 0 | 1 | 2 = 1): string {
  if (deg == null || !Number.isFinite(deg)) return '';
  if (unit === 'gon') return `${fmtFixed(deg / GON, 4 + decimals)} gon`;
  if (unit === 'deg') return `${fmtFixed(deg, 5 + decimals)}°`;
  const sign = deg < 0 ? '-' : '';
  const scale = 10 ** decimals;
  let units = Math.round(Math.abs(deg) * 3600 * scale);
  const d = Math.floor(units / (3600 * scale));
  units -= d * 3600 * scale;
  const m = Math.floor(units / (60 * scale));
  const s = (units - m * 60 * scale) / scale;
  const sText = decimals ? s.toFixed(decimals).padStart(3 + decimals, '0') : String(s).padStart(2, '0');
  return `${sign}${d}°${String(m).padStart(2, '0')}'${sText}"`;
}

const QUADRANT = /^([NSns])\s*(.+?)\s*([EWOew])$/;

/**
 * Grid azimuth from a typed direction. Quadrant bearings are recognised by
 * their letters in any format setting; a bare angle follows the zero direction.
 */
export function parseDirection(text: string, conv: Pick<PlanConventions, 'angleUnit' | 'azimuthZero'>): number | null {
  const s = text.trim();
  const q = QUADRANT.exec(s);
  if (q) {
    const a = parseAngle(q[2]!, conv.angleUnit);
    if (a == null || a < 0 || a > 90) return null;
    const ns = q[1]!.toUpperCase();
    const ew = q[3]!.toUpperCase() === 'W' ? 'W' : 'E';
    if (ns === 'N') return normalizeAzimuth(ew === 'E' ? a : 360 - a);
    return normalizeAzimuth(ew === 'E' ? 180 - a : 180 + a);
  }
  const a = parseAngle(s, conv.angleUnit);
  if (a == null) return null;
  return normalizeAzimuth(conv.azimuthZero === 'south' ? a + 180 : a);
}

/** Display text of a grid azimuth under the conventions. */
export function formatDirection(
  azimuth: number | null | undefined,
  conv: Pick<PlanConventions, 'angleUnit' | 'azimuthZero' | 'directionFormat' | 'angleDecimals'>,
): string {
  if (azimuth == null || !Number.isFinite(azimuth)) return '';
  const az = normalizeAzimuth(azimuth);
  if (conv.directionFormat === 'quadrant') return formatQuadrant(az, conv.angleUnit, conv.angleDecimals);
  const shown = conv.azimuthZero === 'south' ? normalizeAzimuth(az + 180) : az;
  return formatAngle(shown, conv.angleUnit, conv.angleDecimals);
}

export function formatQuadrant(azimuth: number, unit: AngleUnit, decimals: 0 | 1 | 2 = 1): string {
  const az = normalizeAzimuth(azimuth);
  let ns: 'N' | 'S';
  let ew: 'E' | 'W';
  let a: number;
  if (az <= 90) [ns, ew, a] = ['N', 'E', az];
  else if (az <= 180) [ns, ew, a] = ['S', 'E', 180 - az];
  else if (az < 270) [ns, ew, a] = ['S', 'W', az - 180];
  else [ns, ew, a] = ['N', 'W', 360 - az];
  return `${ns} ${formatAngle(a, unit, decimals)} ${ew}`;
}

/** Grid azimuth of the line from `a` to `b` ([E, N]). */
export function azimuthOf(a: readonly [number, number], b: readonly [number, number]): number {
  return normalizeAzimuth((Math.atan2(b[0] - a[0], b[1] - a[1]) * 180) / Math.PI);
}
