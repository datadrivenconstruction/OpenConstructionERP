// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Telematics formatting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ helpers: pure functions, no React, easy to test.
 * Backend Decimals arrive as strings; these turn them into display numbers.
 */

export type ImportKind = 'aemp' | 'csv';

/** Share (0-100) of the engine time that was idle above which a machine is flagged. */
export const IDLE_FLAG_PCT = 30;

export function toNumber(value: string | number | null | undefined): number {
  const n = typeof value === 'number' ? value : Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

/** Inclusive window ending on `today` and covering `days` calendar days, as ISO dates. */
export function lastDaysWindow(days: number, today: Date = new Date()): { date_from: string; date_to: string } {
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const from = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (Math.max(1, days) - 1));
  return { date_from: iso(from), date_to: iso(today) };
}

/** Tailwind text tone for an idle share: amber above the flag line, plain otherwise. */
export function idleTone(idlePct: string | number | null | undefined): string {
  return toNumber(idlePct) > IDLE_FLAG_PCT ? 'text-semantic-warning' : 'text-content-primary';
}

/** Which import endpoint a file belongs to, or null when the extension is not supported. */
export function importKindFor(fileName: string): ImportKind | null {
  const ext = fileName.toLowerCase().split('.').pop() ?? '';
  if (ext === 'xml' || ext === 'json') return 'aemp';
  if (ext === 'csv') return 'csv';
  return null;
}

/** Width (0-100) of a utilisation bar, clamped. */
export function barWidth(pct: string | number | null | undefined): number {
  return Math.min(100, Math.max(0, toNumber(pct)));
}

export interface HoursSplit {
  worked: number;
  idle: number;
  off: number;
}

/** Worked / idle / off hours as shares (0-100) of their sum, for a stacked bar. */
export function hoursShares(h: {
  worked_hours: string | number;
  idle_hours: string | number;
  off_hours: string | number;
}): HoursSplit {
  const worked = toNumber(h.worked_hours);
  const idle = toNumber(h.idle_hours);
  const off = toNumber(h.off_hours);
  const total = worked + idle + off;
  if (total <= 0) return { worked: 0, idle: 0, off: 0 };
  return { worked: (worked / total) * 100, idle: (idle / total) * 100, off: (off / total) * 100 };
}
