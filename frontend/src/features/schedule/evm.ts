// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure derivations for the earned-value (EVM) panel and the 4D snapshot
 * scrubber. No React, no network, no DOM - everything here is unit-testable
 * in isolation (see evm.test.ts).
 *
 * Money values arrive from the wire as Decimal-as-strings; callers format them
 * through `shared/lib/money.ts`. The helpers here only deal with the
 * dimensionless ratios, the health verdict and the snapshot status tallies.
 */
import type { EvmSummary, ScheduleSnapshot } from './api';
import { fmtFixed } from '@/shared/lib/formatters';

/** Performance verdict for an SPI/CPI index relative to the 1.0 baseline. */
export type EvmHealth = 'ahead' | 'on_track' | 'behind' | 'unknown';

/**
 * Classify a performance index (SPI or CPI) into a coarse health band.
 *
 * - `>= 1.0 + EPS`  -> "ahead"  (ahead of schedule / under budget)
 * - within EPS of 1 -> "on_track"
 * - `< 1.0 - EPS`   -> "behind" (behind schedule / over budget)
 * - `null`/non-finite -> "unknown" (no cost data or zero denominator)
 *
 * A small epsilon keeps a 0.999/1.001 rounding wobble from flipping the badge.
 */
export function classifyIndex(index: number | null | undefined): EvmHealth {
  if (index == null || !Number.isFinite(index)) return 'unknown';
  const EPS = 0.005;
  if (index >= 1 + EPS) return 'ahead';
  if (index <= 1 - EPS) return 'behind';
  return 'on_track';
}

/**
 * Format a performance index for display (e.g. 0.8333 -> "0.83").
 * Returns an em-dash-free placeholder for an unknown index.
 */
export function formatIndex(index: number | null | undefined, placeholder = '-'): string {
  if (index == null || !Number.isFinite(index)) return placeholder;
  return fmtFixed(index, 2);
}

/**
 * Is a variance favourable? For both schedule variance (SV = EV - PV) and cost
 * variance (CV = EV - AC), a non-negative value is favourable (ahead / under).
 * Operates on the numeric form (callers coerce the wire string via toNum).
 */
export function isVarianceFavourable(variance: number): boolean {
  return variance >= 0;
}

/** True when the summary carries usable cost data to render the money KPIs. */
export function hasEvmCostData(summary: EvmSummary | null | undefined): boolean {
  return Boolean(summary?.has_cost_data);
}

/** Canonical 4D status keys, ordered worst-first for legends / sorting. */
export const SNAPSHOT_STATUS_ORDER = [
  'delayed',
  'in_progress',
  'not_started',
  'ahead_of_schedule',
  'completed',
] as const;

export type SnapshotStatus = (typeof SNAPSHOT_STATUS_ORDER)[number];

/** One status bucket with its element count, used by the snapshot legend. */
export interface SnapshotStatusCount {
  status: string;
  count: number;
}

/**
 * Tally a snapshot's `{element_id: status}` map into per-status counts, in the
 * canonical worst-first order. Statuses not in the canonical list are appended
 * (alphabetically) after the known ones so nothing is silently dropped.
 */
export function tallySnapshot(
  snapshot: ScheduleSnapshot | null | undefined,
): SnapshotStatusCount[] {
  const counts = new Map<string, number>();
  const elements = snapshot?.elements ?? {};
  for (const status of Object.values(elements)) {
    counts.set(status, (counts.get(status) ?? 0) + 1);
  }
  const ordered: SnapshotStatusCount[] = [];
  for (const status of SNAPSHOT_STATUS_ORDER) {
    if (counts.has(status)) {
      ordered.push({ status, count: counts.get(status)! });
      counts.delete(status);
    }
  }
  // Append any unknown statuses deterministically.
  for (const status of Array.from(counts.keys()).sort()) {
    ordered.push({ status, count: counts.get(status)! });
  }
  return ordered;
}

/** Total number of linked elements represented in a snapshot. */
export function snapshotTotal(snapshot: ScheduleSnapshot | null | undefined): number {
  return Object.keys(snapshot?.elements ?? {}).length;
}

/**
 * Clamp an ISO date (YYYY-MM-DD) into the inclusive [min, max] window. Used by
 * the snapshot scrubber so the chosen data date can never fall outside the
 * schedule span. Invalid / missing bounds pass the value through unchanged.
 */
export function clampDateIso(value: string, min?: string | null, max?: string | null): string {
  if (!value) return value;
  let out = value;
  if (min && out < min) out = min;
  if (max && out > max) out = max;
  return out;
}

/**
 * Derive an inclusive [start, end] ISO date window from a schedule's bounds,
 * defaulting to a sensible window when either bound is missing so the scrubber
 * always has a usable range. ``today`` lets tests inject a deterministic clock.
 */
export function deriveScrubberRange(
  startDate: string | null | undefined,
  endDate: string | null | undefined,
  today: string,
): { min: string; max: string } {
  const start = (startDate || '').slice(0, 10);
  const end = (endDate || '').slice(0, 10);
  if (start && end) {
    // Guard against an inverted range (bad data): swap so min <= max.
    return start <= end ? { min: start, max: end } : { min: end, max: start };
  }
  if (start) return { min: start, max: start > today ? start : today };
  if (end) return { min: end < today ? end : today, max: end };
  return { min: today, max: today };
}

/**
 * Whole-day count between two ISO (YYYY-MM-DD) dates, UTC-safe so it never
 * drifts by a day across DST boundaries. Returns 0 for unparseable input.
 * Used to map the snapshot scrubber's slider position to a date.
 */
export function daysBetweenIso(from: string, to: string): number {
  const f = Date.parse(`${from}T00:00:00Z`);
  const t = Date.parse(`${to}T00:00:00Z`);
  if (Number.isNaN(f) || Number.isNaN(t)) return 0;
  return Math.round((t - f) / 86_400_000);
}

/**
 * Add ``days`` whole days to an ISO (YYYY-MM-DD) date, UTC-safe. Returns the
 * input unchanged when it cannot be parsed.
 */
export function addDaysIso(from: string, days: number): string {
  const f = Date.parse(`${from}T00:00:00Z`);
  if (Number.isNaN(f)) return from;
  return new Date(f + days * 86_400_000).toISOString().slice(0, 10);
}
