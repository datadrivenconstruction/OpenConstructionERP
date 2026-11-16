// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure geometry and tone for the cap meter. Numbers arrive as decimal strings from the
 * server; the meter only places them on one scale (0 .. max(cap, used)).
 */

export type CapTone = 'neutral' | 'warning' | 'error';

export interface CapMeterInput {
  cap: string | null;
  committed: string;
  certified: string;
  threshold_pct: string;
  min_value?: string | null;
  term_elapsed_pct?: string | null;
}

export interface CapMeterGeometry {
  /** Width in percent of the bar for the certified part. */
  certified: number;
  /** Committed but not yet certified. */
  pending: number;
  /** Marker positions in percent of the bar, or null. */
  threshold: number | null;
  minimum: number | null;
  capMark: number | null;
  termElapsed: number | null;
  pct: number | null;
  tone: CapTone;
}

const num = (v: string | null | undefined): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

const clampPct = (n: number): number => Math.max(0, Math.min(100, n));

export function capTone(pct: number | null, thresholdPct: number): CapTone {
  if (pct == null) return 'neutral';
  if (pct > 100) return 'error';
  if (pct >= thresholdPct) return 'warning';
  return 'neutral';
}

export function capMeterGeometry(input: CapMeterInput): CapMeterGeometry {
  const cap = input.cap == null ? null : num(input.cap);
  const committed = num(input.committed);
  const certified = Math.min(num(input.certified), committed);
  const threshold = num(input.threshold_pct) || 80;
  if (!cap) {
    return {
      certified: 0,
      pending: 0,
      threshold: null,
      minimum: null,
      capMark: null,
      termElapsed: input.term_elapsed_pct == null ? null : clampPct(num(input.term_elapsed_pct)),
      pct: null,
      tone: 'neutral',
    };
  }
  // Over the cap the scale grows so the overrun stays visible and the cap mark moves left.
  const scale = Math.max(cap, committed);
  const pct = Math.round((committed / cap) * 10000) / 100;
  const minimum = input.min_value ? num(input.min_value) : 0;
  return {
    certified: clampPct((certified / scale) * 100),
    pending: clampPct(((committed - certified) / scale) * 100),
    threshold: clampPct(((cap * threshold) / 100 / scale) * 100),
    minimum: minimum > 0 ? clampPct((minimum / scale) * 100) : null,
    capMark: clampPct((cap / scale) * 100),
    termElapsed: input.term_elapsed_pct == null ? null : clampPct(num(input.term_elapsed_pct)),
    pct,
    tone: capTone(pct, threshold),
  };
}
