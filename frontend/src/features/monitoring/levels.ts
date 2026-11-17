// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { BadgeVariant } from '@/shared/ui/Badge';
import type { Level, SeriesEntry, Thresholds } from './api';

export const LEVELS: Level[] = ['ok', 'alert', 'action', 'alarm'];

export const LEVEL_DEFAULT: Record<Level, string> = {
  none: 'No profile',
  ok: 'OK',
  alert: 'Alert',
  action: 'Action',
  alarm: 'Alarm',
};

export function levelVariant(level: Level): BadgeVariant {
  if (level === 'alarm' || level === 'action') return 'error';
  if (level === 'alert') return 'warning';
  if (level === 'ok') return 'success';
  return 'neutral';
}

/** Displacement in mm with one decimal and a real minus sign; empty when unknown. */
export function fmtMm(v: number | null | undefined): string {
  return v == null ? '' : v.toFixed(1).replace('-', '−');
}

/** Rate in mm/day with two decimals. */
export function fmtRate(v: number | null | undefined): string {
  return v == null ? '' : v.toFixed(2).replace('-', '−');
}

export interface Band {
  level: 'alert' | 'action' | 'alarm';
  mm: number;
}

/** The displacement limits that are set, rising, as chart bands. */
export function bandLines(t: Thresholds | null): Band[] {
  if (!t) return [];
  const out: Band[] = [];
  if (t.alert_mm != null) out.push({ level: 'alert', mm: t.alert_mm });
  if (t.action_mm != null) out.push({ level: 'action', mm: t.action_mm });
  if (t.alarm_mm != null) out.push({ level: 'alarm', mm: t.alarm_mm });
  return out;
}

export interface ChartPoint {
  x: number;
  y: number;
  level: Level;
}

/**
 * Map the series to SVG space. The vertical range always holds the bands so a
 * reading far from a limit is seen to be far. Settlement runs down: when every
 * displacement is negative the bands are drawn below zero too.
 */
export function chartGeometry(
  series: SeriesEntry[],
  bands: { mm: number }[],
  width: number,
  height: number,
  pad = 28,
): { points: ChartPoint[]; yOf: (mm: number) => number; sign: 1 | -1 } {
  const values = series.map((s) => s.displacement_mm ?? 0);
  const sign: 1 | -1 = values.some((v) => v < 0) && !values.some((v) => v > 0) ? -1 : 1;
  const all = [0, ...values, ...bands.map((b) => sign * b.mm)];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = hi - lo || 1;
  const yOf = (mm: number) => pad + ((hi - mm) / span) * (height - 2 * pad);
  const times = series.map((s) => new Date(s.at).getTime());
  const t0 = Math.min(...times);
  const tspan = Math.max(...times) - t0 || 1;
  const points = series.map((s, i) => ({
    x: series.length === 1 ? width / 2 : pad + (((times[i] ?? t0) - t0) / tspan) * (width - 2 * pad),
    y: yOf(s.displacement_mm ?? 0),
    level: s.level,
  }));
  return { points, yOf, sign };
}
