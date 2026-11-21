// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Distances, areas, coordinates and chainages. Every stored value is metres
 * on the grid; these functions only convert for display and input.
 */

import { fmtFixed } from '@/shared/lib/formatters';
import type { AreaUnit, AxisConvention, ChainageFormat, DistancePrecision, LinearUnit, PlanConventions } from './conventions';

export const METRES_PER: Record<LinearUnit, number> = { m: 1, ft: 0.3048, ftUS: 1200 / 3937 };
export const LINEAR_SYMBOL: Record<LinearUnit, string> = { m: 'm', ft: 'ft', ftUS: 'US ft' };
export const SQ_METRES_PER: Record<AreaUnit, number> = { m2: 1, ha: 10000, acre: 4046.8564224, ft2: 0.09290304 };
export const AREA_SYMBOL: Record<AreaUnit, string> = { m2: 'm²', ha: 'ha', acre: 'ac', ft2: 'sq ft' };
const AREA_DECIMALS: Record<AreaUnit, number> = { m2: 2, ha: 4, acre: 4, ft2: 1 };
const PRECISION_DECIMALS: Record<DistancePrecision, number> = { mm: 3, cm: 2, '0.01ft': 2, '0.001ft': 3 };

export function toMetres(value: number, unit: LinearUnit): number {
  return value * METRES_PER[unit];
}

export function fromMetres(metres: number, unit: LinearUnit): number {
  return metres / METRES_PER[unit];
}

export function distanceDecimals(conv: Pick<PlanConventions, 'precision'>): number {
  return PRECISION_DECIMALS[conv.precision];
}

/** "25.000 m" in the reader's number format. */
export function formatDistance(metres: number | null | undefined, conv: Pick<PlanConventions, 'linearUnit' | 'precision'>, withUnit = true): string {
  if (metres == null || !Number.isFinite(metres)) return '';
  const text = fmtFixed(fromMetres(metres, conv.linearUnit), distanceDecimals(conv));
  return withUnit ? `${text} ${LINEAR_SYMBOL[conv.linearUnit]}` : text;
}

/** A distance for an editable field: canonical digits, no grouping. */
export function inputDistance(metres: number, conv: Pick<PlanConventions, 'linearUnit' | 'precision'>): string {
  return fromMetres(metres, conv.linearUnit).toFixed(distanceDecimals(conv));
}

const DIST_SUFFIX: [RegExp, LinearUnit][] = [
  [/\s*(?:us\s*ft|usft|sft|survey\s*ft)$/i, 'ftUS'],
  [/\s*(?:ift|ft|feet|')$/i, 'ft'],
  [/\s*m$/i, 'm'],
];

/** Metres from typed text; a unit suffix (m, ft, ', US ft) wins over the setting. */
export function parseDistance(text: string, conv: Pick<PlanConventions, 'linearUnit'>): number | null {
  let s = text.trim();
  if (!s) return null;
  let unit = conv.linearUnit;
  for (const [re, u] of DIST_SUFFIX) {
    if (re.test(s)) {
      s = s.replace(re, '');
      unit = u;
      break;
    }
  }
  s = s.replace(/\s/g, '').replace(',', '.');
  if (!/^[-+]?(\d+\.?\d*|\.\d+)$/.test(s)) return null;
  return toMetres(Number(s), unit);
}

export function formatArea(m2: number | null | undefined, conv: Pick<PlanConventions, 'areaUnit'>, withUnit = true): string {
  if (m2 == null || !Number.isFinite(m2)) return '';
  const text = fmtFixed(m2 / SQ_METRES_PER[conv.areaUnit], AREA_DECIMALS[conv.areaUnit]);
  return withUnit ? `${text} ${AREA_SYMBOL[conv.areaUnit]}` : text;
}

/** Grid distance from a ground distance: grid = ground x CSF. */
export function groundToGrid(ground: number, csf: number | null | undefined): number {
  return csf && Number.isFinite(csf) ? ground * csf : ground;
}

export function gridToGround(grid: number, csf: number | null | undefined): number {
  return csf && Number.isFinite(csf) ? grid / csf : grid;
}

/** Whether ground and grid differ enough (over 10 ppm) to show both. */
export function csfMatters(csf: number | null | undefined): boolean {
  return !!csf && Math.abs(csf - 1) > 10e-6;
}

// ── Axes ──────────────────────────────────────────────────────────────────

export interface AxisSpec {
  /** Which grid component sits in the first column. */
  first: 'e' | 'n';
  labels: [string, string];
}

const AXES: Record<AxisConvention, AxisSpec> = {
  EN: { first: 'e', labels: ['E', 'N'] },
  NE: { first: 'n', labels: ['N', 'E'] },
  XY: { first: 'n', labels: ['X', 'Y'] },
  YX: { first: 'e', labels: ['Y', 'X'] },
};

export function axisSpec(axis: AxisConvention): AxisSpec {
  return AXES[axis];
}

/** Labels of the easting and northing under the convention: {e: 'Y', n: 'X'} for geodetic axes. */
export function axisLabelFor(axis: AxisConvention): { e: string; n: string } {
  const s = AXES[axis];
  return s.first === 'e' ? { e: s.labels[0], n: s.labels[1] } : { e: s.labels[1], n: s.labels[0] };
}

/** [E, N] in display order. */
export function toDisplayOrder(e: number, n: number, axis: AxisConvention): [number, number] {
  return AXES[axis].first === 'e' ? [e, n] : [n, e];
}

/** [E, N] from a pair in display order. */
export function fromDisplayOrder(a: number, b: number, axis: AxisConvention): [number, number] {
  return AXES[axis].first === 'e' ? [a, b] : [b, a];
}

/** A coordinate in the display unit and precision, grouped for reading. */
export function formatCoord(metres: number | null | undefined, conv: Pick<PlanConventions, 'linearUnit' | 'precision'>): string {
  return formatDistance(metres, conv, false);
}

/** "E 389 012.345  N 5 819 004.210" in the convention's order and letters. */
export function formatCoordPair(e: number, n: number, conv: Pick<PlanConventions, 'axis' | 'linearUnit' | 'precision'>): string {
  const s = AXES[conv.axis];
  const [a, b] = toDisplayOrder(e, n, conv.axis);
  return `${s.labels[0]} ${formatCoord(a, conv)}  ${s.labels[1]} ${formatCoord(b, conv)}`;
}

/** Two or three numbers in display order -> grid [E, N, Z?] in metres. */
export function parseCoordPair(text: string, conv: Pick<PlanConventions, 'axis' | 'linearUnit'>): number[] | null {
  const parts = text.trim().split(/[\s;]+|,\s+/).filter(Boolean).map((p) => Number(p.replace(',', '.')));
  if (parts.length < 2 || parts.length > 3 || parts.some((p) => !Number.isFinite(p))) return null;
  const k = METRES_PER[conv.linearUnit];
  const [e, n] = fromDisplayOrder(parts[0]! * k, parts[1]! * k, conv.axis);
  return parts.length === 3 ? [e, n, parts[2]! * k] : [e, n];
}

/**
 * Which grid component a point-file column holds, given its header. X and Y
 * follow the convention: under XY/YX the X column is the northing.
 */
export function columnRole(header: string, axis: AxisConvention): 'e' | 'n' | 'z' | null {
  const h = header.trim().toLowerCase();
  if (['e', 'east', 'easting', 'rechtswert', 'rw'].includes(h)) return 'e';
  if (['n', 'north', 'northing', 'hochwert', 'hw'].includes(h)) return 'n';
  if (['z', 'h', 'elev', 'elevation', 'height'].includes(h)) return 'z';
  const geodetic = axis === 'XY' || axis === 'YX';
  if (h === 'x') return geodetic ? 'n' : 'e';
  if (h === 'y') return geodetic ? 'e' : 'n';
  return null;
}

// ── Chainage ──────────────────────────────────────────────────────────────

/**
 * Chainage text: metric 1+234.567, imperial 12+34.56 (100 ft stations in the
 * project foot), km "km 1.235".
 */
export function formatChainage(
  metres: number | null | undefined,
  format: ChainageFormat,
  conv: Pick<PlanConventions, 'linearUnit'> = { linearUnit: 'ft' },
  decimals?: number,
): string {
  if (metres == null || !Number.isFinite(metres)) return '';
  const sign = metres < 0 ? '-' : '';
  const abs = Math.abs(metres);
  if (format === 'km') return `${sign}km ${fmtFixed(abs / 1000, decimals ?? 3)}`;
  if (format === 'imperial') {
    const unit = conv.linearUnit === 'm' ? 'ft' : conv.linearUnit;
    const d = decimals ?? 2;
    const ft = Number(fromMetres(abs, unit).toFixed(d));
    const station = Math.floor(ft / 100);
    const rest = (ft - station * 100).toFixed(d).padStart(3 + d, '0');
    return `${sign}${station}+${rest}`;
  }
  const d = decimals ?? 3;
  const m = Number(abs.toFixed(d));
  const km = Math.floor(m / 1000);
  const rest = (m - km * 1000).toFixed(d).padStart(4 + d, '0');
  return `${sign}${km}+${rest}`;
}

/** Metres from chainage text in any of the three forms; `format` decides what a plus means. */
export function parseChainage(
  text: string,
  format: ChainageFormat,
  conv: Pick<PlanConventions, 'linearUnit'> = { linearUnit: 'ft' },
): number | null {
  const s = text.trim().replace(',', '.');
  const km = /^(-?)\s*km\s*(\d+(?:\.\d*)?)$/i.exec(s);
  if (km) return (km[1] ? -1 : 1) * Number(km[2]) * 1000;
  const plus = /^(-?)(\d+)\+(\d+(?:\.\d*)?)$/.exec(s);
  if (plus) {
    const sign = plus[1] ? -1 : 1;
    if (format === 'imperial') {
      const unit = conv.linearUnit === 'm' ? 'ft' : conv.linearUnit;
      return sign * toMetres(Number(plus[2]) * 100 + Number(plus[3]), unit);
    }
    return sign * (Number(plus[2]) * 1000 + Number(plus[3]));
  }
  if (/^-?\d+(?:\.\d*)?$/.test(s)) {
    const v = Number(s);
    if (format === 'km') return v * 1000;
    if (format === 'imperial') return toMetres(v, conv.linearUnit === 'm' ? 'ft' : conv.linearUnit);
    return v;
  }
  return null;
}
