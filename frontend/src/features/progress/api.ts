// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API client for the physical progress-tracking module.
 *
 * Backed by /api/v1/progress/ - see backend/app/modules/progress/router.py and
 * schemas.py. The shapes here mirror the Pydantic response models exactly so
 * the page can drop straight onto the API.
 *
 * Two data families with different number contracts:
 *   - S-curve and cumulative percentages are plain floats (0-100), safe to
 *     render and chart directly.
 *   - Quantity-variance figures are Decimal serialised as STRINGS (never
 *     numbers) to match the BOQ position storage convention. Keep them typed
 *     as ``string`` and format at the edge; only ``parseFloat`` a percentage
 *     for a progress-bar width, never do money/quantity math on them here.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

const BASE = '/v1/progress';

/* ── S-curve (actual vs planned cumulative percent over periods) ─────────── */

/**
 * One point on the physical-progress S-curve. ``actual_cumulative_pct`` comes
 * from recorded field entries; ``planned_cumulative_pct`` is null when no plan
 * entry exists for that period (plot actual only in that case). Both are plain
 * percentages in [0, 100].
 *
 * Mirrors backend SCurvePoint.
 */
export interface SCurvePoint {
  period_label: string;
  actual_cumulative_pct: number;
  planned_cumulative_pct: number | null;
}

/** Actual-vs-planned S-curve for a project. Mirrors backend SCurveResponse. */
export interface SCurveResponse {
  project_id: string;
  points: SCurvePoint[];
}

/* ── Cumulative (per-period deltas + running cumulative percent) ─────────── */

/**
 * Progress for a single period: the increase during the period, the running
 * cumulative percent at its end, and how many entries fed it. All percentages
 * are plain floats.
 *
 * Mirrors backend PeriodProgress.
 */
export interface PeriodProgress {
  period_label: string;
  delta_pct: number;
  cumulative_pct: number;
  entry_count: number;
}

/**
 * Per-period breakdown and cumulative rollup for a project (or a single BOQ
 * position when ``boq_position_id`` is set).
 *
 * Mirrors backend CumulativeProgressResponse.
 */
export interface CumulativeProgressResponse {
  project_id: string;
  boq_position_id: string | null;
  periods: PeriodProgress[];
  current_cumulative_pct: number;
}

/* ── Quantity variance (design vs earned quantity) ──────────────────────── */

/**
 * Design-vs-earned quantity variance for one BOQ position.
 *
 * IMPORTANT: ``design_quantity`` / ``earned_quantity`` / ``percent_complete`` /
 * ``variance`` / ``variance_percent`` are Decimal serialised as STRINGS, not
 * numbers. Format them for display; never do float math on them beyond a
 * ``parseFloat`` for a progress-bar width. ``variance_percent`` is null when
 * the design quantity is zero (guarded division). ``status`` is one of
 * ``on_target`` / ``over_run`` / ``under_run``.
 *
 * Mirrors backend PositionQuantityVarianceItem.
 */
export interface PositionQuantityVarianceItem {
  boq_position_id: string;
  ordinal: string | null;
  description: string | null;
  unit: string | null;
  design_quantity: string;
  earned_quantity: string;
  percent_complete: string;
  variance: string;
  variance_percent: string | null;
  status: string;
  is_over_run: boolean;
  is_under_run: boolean;
}

/**
 * Project-level rollup of quantity variance across positions. The ``*_total``
 * fields are Decimal-as-string; ``variance_percent`` is null when the design
 * total is zero.
 *
 * Mirrors backend QuantityVarianceRollupResponse.
 */
export interface QuantityVarianceRollup {
  position_count: number;
  over_run_count: number;
  under_run_count: number;
  on_target_count: number;
  design_quantity_total: string;
  earned_quantity_total: string;
  variance_total: string;
  variance_percent: string | null;
}

/**
 * Full quantity-variance report for a project: per-position rows + rollup.
 *
 * Mirrors backend QuantityVarianceResponse.
 */
export interface QuantityVarianceResponse {
  project_id: string;
  positions: PositionQuantityVarianceItem[];
  rollup: QuantityVarianceRollup;
}

/* ── Client functions ───────────────────────────────────────────────────── */

/**
 * Fetch the physical-progress S-curve (actual vs planned cumulative percent
 * over periods) for a project.
 */
export function getProgressSCurve(projectId: string): Promise<SCurveResponse> {
  return apiGet<SCurveResponse>(
    `${BASE}/s-curve/?project_id=${encodeURIComponent(projectId)}`,
  );
}

/**
 * Fetch the per-period completion deltas and running cumulative percent for a
 * project.
 */
export function getProgressCumulative(
  projectId: string,
): Promise<CumulativeProgressResponse> {
  return apiGet<CumulativeProgressResponse>(
    `${BASE}/cumulative/?project_id=${encodeURIComponent(projectId)}`,
  );
}

/**
 * Fetch the design-vs-earned quantity variance (per-position rows + rollup)
 * for a project. Requires the ``progress.read`` permission - a caller without
 * it gets a 403.
 */
export function getQuantityVariance(
  projectId: string,
): Promise<QuantityVarianceResponse> {
  return apiGet<QuantityVarianceResponse>(
    `${BASE}/quantity-variance/?project_id=${encodeURIComponent(projectId)}`,
  );
}

/* ── Recording an observation ────────────────────────────────────────────── */

/**
 * A percent-complete observation, as the server accepts it.
 *
 * Mirrors backend ``ProgressEntryCreate``. Two fields carry more meaning than
 * their types suggest:
 *
 * ``boq_position_id`` is nullable, and the two cases are genuinely different
 * readings rather than one with a shortcut. A position id records how far one
 * line item has got, and those readings are what the project percentage is
 * rolled up from. Omitting it records an overall reading for the project,
 * which is the fallback the rollup uses only when no line has been measured -
 * so a project-level entry alongside position readings keeps its own row and
 * its entry count but does not move the headline number.
 *
 * ``period_label`` is a free string capped at 20 characters and is the axis
 * everything is grouped by, so it has to be written the same way every time.
 * The dialog defaults it to the current ISO month for exactly that reason.
 */
export interface ProgressEntryCreate {
  project_id: string;
  boq_position_id?: string | null;
  period_label: string;
  /** Percent in [0, 100]; the server rejects anything outside it. */
  percent_complete: number;
  notes?: string | null;
}

/** The stored observation, as echoed back. */
export interface ProgressEntryResponse {
  id: string;
  project_id: string;
  boq_position_id: string | null;
  period_label: string;
  percent_complete: number;
  notes: string | null;
  recorded_at: string;
}

/**
 * Record one percent-complete observation.
 *
 * Entries are append-only: correcting a reading means recording the corrected
 * value again in the same period, not editing the old row. Be aware that the
 * project percentage takes the MAXIMUM reading within a period, so a downward
 * correction does not currently lower it, while the contracts module reads the
 * latest. That inconsistency is known and is a decision above this layer, so
 * do not paper over it here.
 */
export function createProgressEntry(
  data: ProgressEntryCreate,
): Promise<ProgressEntryResponse> {
  return apiPost<ProgressEntryResponse>(`${BASE}/entries/`, data);
}
