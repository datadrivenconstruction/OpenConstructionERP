// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Deviation arrows of measured stakes and monitoring vectors. A deviation of a
 * few millimetres is invisible at plan scale, so the arrow is drawn
 * exaggerated: its plan length is the deviation times the scale. The legend
 * states the scale in words ("1 m of arrow = 10 mm") so nobody reads the
 * arrow as a real offset.
 *
 * Colour and shape both carry the verdict, so it reads without colour too.
 */

import type { GridXY, PlanFeature } from '../types';
import type { MapToken } from '../cartography';

export const ARROW_SCALES = [10, 50, 100, 500] as const;
export type ArrowScale = (typeof ARROW_SCALES)[number];
export const DEFAULT_ARROW_SCALE: ArrowScale = 100;

export type StakeVerdict = 'pass' | 'fail' | 'no_tolerance' | 'open';
export type VerdictShape = 'circle' | 'square' | 'diamond' | 'cross';

export interface VerdictStyle {
  token: MapToken;
  shape: VerdictShape;
  /** Semantic class family for the DOM legend and chips. */
  semantic: 'success' | 'error' | 'warning' | 'neutral';
}

const STYLES: Record<StakeVerdict, VerdictStyle> = {
  pass: { token: 'success', shape: 'circle', semantic: 'success' },
  fail: { token: 'error', shape: 'square', semantic: 'error' },
  no_tolerance: { token: 'warning', shape: 'diamond', semantic: 'warning' },
  open: { token: 'ink-2', shape: 'cross', semantic: 'neutral' },
};

export function verdictStyle(v: StakeVerdict | string | null | undefined): VerdictStyle {
  return STYLES[(v ?? 'open') as StakeVerdict] ?? STYLES.open;
}

export interface Arrow {
  /** From the design point to the exaggerated end. */
  shaft: [GridXY, GridXY];
  /** Closed triangle of the head (3 vertices), empty for a zero deviation. */
  head: GridXY[];
  /** Plan length of the drawn arrow in metres. */
  planLength: number;
  /** True deviation in millimetres. */
  devMm: number;
}

/**
 * The arrow from `design` towards `measured`, `scale` times the true offset.
 * The head is 22 % of the shaft with a 28 degree half angle, never longer than
 * `maxHead` plan metres, so short arrows still show which way they point.
 */
export function deviationArrow(design: GridXY, measured: GridXY, scale: number, maxHead = 1.2): Arrow {
  const de = measured[0] - design[0];
  const dn = measured[1] - design[1];
  const dev = Math.hypot(de, dn);
  const end: GridXY = [design[0] + de * scale, design[1] + dn * scale];
  const len = dev * scale;
  if (len < 1e-9) return { shaft: [design, design], head: [], planLength: 0, devMm: 0 };
  const ux = de / dev;
  const uy = dn / dev;
  const h = Math.min(len * 0.22, maxHead);
  const w = h * Math.tan((28 * Math.PI) / 180);
  const base: GridXY = [end[0] - ux * h, end[1] - uy * h];
  const head: GridXY[] = [end, [base[0] - uy * w, base[1] + ux * w], [base[0] + uy * w, base[1] - ux * w]];
  return { shaft: [design, base], head, planLength: len, devMm: Math.round(dev * 10000) / 10 };
}

/** Millimetres of deviation that one plan metre of arrow stands for. */
export function mmPerArrowMetre(scale: number): number {
  return 1000 / scale;
}

/** Plan length (m) of an arrow that stands for `mm` of deviation. */
export function arrowLengthFor(mm: number, scale: number): number {
  return (mm / 1000) * scale;
}

export interface StakeForArrow {
  id: string;
  pointId: string;
  design: GridXY;
  measured: GridXY | null;
  verdict: StakeVerdict;
  dE?: number | null;
  dN?: number | null;
  dZ?: number | null;
}

/** Plan features: one design cross per stake, an as-staked dot and an exaggerated arrow when measured. */
export function stakeFeatures(stakes: readonly StakeForArrow[], scale: number): PlanFeature[] {
  const out: PlanFeature[] = [];
  for (const s of stakes) {
    const vs = verdictStyle(s.verdict);
    const props = {
      label: s.pointId,
      verdict: s.verdict,
      shape: vs.shape,
      colour: vs.token,
      de_mm: s.dE ?? null,
      dn_mm: s.dN ?? null,
      dz_mm: s.dZ ?? null,
    };
    out.push({ id: `stake:${s.id}`, layer: 'stakes', geometry: { type: 'Point', coordinates: s.design }, properties: { ...props, role: 'design' }, entityType: 'stake', entityId: s.id });
    if (!s.measured) continue;
    const a = deviationArrow(s.design, s.measured, scale);
    out.push({ id: `stake-asb:${s.id}`, layer: 'stakes', geometry: { type: 'Point', coordinates: s.measured }, properties: { ...props, role: 'measured', label: '' } });
    if (!a.head.length) continue;
    out.push({ id: `stake-arrow:${s.id}`, layer: 'stakes', geometry: { type: 'LineString', coordinates: a.shaft }, properties: { ...props, role: 'arrow', label: '' } });
    out.push({ id: `stake-head:${s.id}`, layer: 'stakes', geometry: { type: 'Polygon', coordinates: [a.head] }, properties: { ...props, role: 'head', label: '' } });
  }
  return out;
}

/** Counts per verdict for the filter chips. */
export function verdictCounts(stakes: readonly { verdict: StakeVerdict }[]): Record<StakeVerdict, number> {
  const out: Record<StakeVerdict, number> = { pass: 0, fail: 0, no_tolerance: 0, open: 0 };
  for (const s of stakes) out[s.verdict] = (out[s.verdict] ?? 0) + 1;
  return out;
}
