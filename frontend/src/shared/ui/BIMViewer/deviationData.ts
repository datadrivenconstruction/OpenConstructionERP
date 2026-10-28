// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Scan-vs-design deviation overlay - API client + pure legend derivation.
 *
 * The point-cloud backend computes how far an as-built laser scan deviates
 * from the design model and stores the result per aligned scan. This module
 * fetches that per-model rollup
 * (`GET /api/v1/pointcloud/deviation?project_id&model_id`) and turns it into
 * the rows the viewer's deviation legend paints. The heavy point-to-mesh math
 * is NOT here and is never recomputed on the client - we only surface the
 * already-computed verdict.
 *
 * The legend derivation (`buildDeviationLegend`) is a *pure function* over a
 * fetched summary so it is unit-tested independently of React / the network.
 */

import { apiGet } from '@/shared/lib/api';
import { toNum } from '@/shared/lib/money';

/** Traffic-light verdict codes, mirrored from
 *  backend/app/modules/pointcloud/deviation.py. */
export type DeviationSeverity = 'unknown' | 'within' | 'warning' | 'over';

/** One scan-vs-design deviation result for the open design model. Decimal
 *  figures (rms_error, coverage_pct, hole_area, confidence, tier_tolerance_mm)
 *  arrive as JSON strings, mirroring the backend Decimal-as-string contract. */
export interface ScanDeviationItem {
  registration_id: string;
  scan_id: string;
  target_ref: string;
  accuracy_tier: string;
  tier_tolerance_mm: string | null;
  rms_error: string | null;
  out_of_tolerance_count: number;
  coverage_pct: string | null;
  hole_area: string | null;
  confidence: string | null;
  deviation_map_uri: string | null;
  severity: DeviationSeverity;
  severity_color: string;
  created_at: string;
}

/** Per-model deviation rollup that drives the overlay + legend. */
export interface ScanDeviationSummary {
  model_id: string;
  project_id: string;
  has_deviation: boolean;
  worst_severity: DeviationSeverity;
  worst_severity_color: string;
  items: ScanDeviationItem[];
  total: number;
}

/**
 * Fetch the scan-vs-design deviation rollup for one design model.
 *
 * Returns a well-formed summary with `has_deviation=false` when the model has
 * no aligned scans (the backend never 404s that case), so the caller can
 * simply not render the overlay.
 */
export async function fetchModelDeviation(
  projectId: string,
  modelId: string,
): Promise<ScanDeviationSummary> {
  const q = new URLSearchParams({ project_id: projectId, model_id: modelId });
  return apiGet<ScanDeviationSummary>(`/v1/pointcloud/deviation?${q.toString()}`);
}

/** A translator function compatible with i18next's `t`. */
export type TranslateFn = (
  key: string,
  opts?: { defaultValue?: string } & Record<string, unknown>,
) => string;

/** One row of the deviation legend: a coloured swatch, a label, and how many
 *  aligned scans landed in that band. */
export interface DeviationLegendRow {
  severity: DeviationSeverity;
  label: string;
  hex: string;
  count: number;
}

/** Fixed fallback colours per severity, matching the backend palette and the
 *  BIM viewer's validation legend (red / amber / green / grey). Used when a
 *  row carries no explicit `severity_color`. */
export const DEVIATION_SEVERITY_HEX: Record<DeviationSeverity, string> = {
  within: '#10b981',
  warning: '#f59e0b',
  over: '#ef4444',
  unknown: '#cbd5e1',
};

/** Stable order the legend lists bands in: worst first so the most urgent
 *  reads at the top. */
const SEVERITY_ORDER: DeviationSeverity[] = ['over', 'warning', 'within', 'unknown'];

/**
 * Build the deviation legend rows from a fetched summary.
 *
 * Counts how many aligned scans fall in each severity band, drops bands with
 * no scans, and labels each via `t`. Pure - no React, no fetch. Returns an
 * empty array when there is no deviation data, so the caller renders nothing.
 */
export function buildDeviationLegend(
  summary: ScanDeviationSummary | null | undefined,
  t: TranslateFn,
): DeviationLegendRow[] {
  if (!summary || !summary.has_deviation || summary.items.length === 0) {
    return [];
  }

  const counts = new Map<DeviationSeverity, number>();
  const colors = new Map<DeviationSeverity, string>();
  for (const item of summary.items) {
    const sev = item.severity;
    counts.set(sev, (counts.get(sev) ?? 0) + 1);
    // Prefer the server-sent colour (single source of truth) but only record
    // the first one seen per band so later rows can't flip it.
    if (!colors.has(sev) && item.severity_color) {
      colors.set(sev, item.severity_color);
    }
  }

  const labels: Record<DeviationSeverity, string> = {
    over: t('bim.deviation_over', { defaultValue: 'Over tolerance' }),
    warning: t('bim.deviation_warning', { defaultValue: 'Local deviation' }),
    within: t('bim.deviation_within', { defaultValue: 'Within tolerance' }),
    unknown: t('bim.deviation_unknown', { defaultValue: 'Not measured' }),
  };

  const rows: DeviationLegendRow[] = [];
  for (const sev of SEVERITY_ORDER) {
    const count = counts.get(sev) ?? 0;
    if (count === 0) continue;
    rows.push({
      severity: sev,
      label: labels[sev],
      hex: colors.get(sev) || DEVIATION_SEVERITY_HEX[sev],
      count,
    });
  }
  return rows;
}

/**
 * One-line headline summarising the model's worst deviation band for the
 * overlay banner, e.g. "As-built scan deviates beyond tolerance". Pure.
 */
export function deviationHeadline(
  summary: ScanDeviationSummary | null | undefined,
  t: TranslateFn,
): string {
  const sev = summary?.worst_severity ?? 'unknown';
  switch (sev) {
    case 'over':
      return t('bim.deviation_headline_over', {
        defaultValue: 'As-built scan deviates beyond tolerance',
      });
    case 'warning':
      return t('bim.deviation_headline_warning', {
        defaultValue: 'As-built scan has local deviations',
      });
    case 'within':
      return t('bim.deviation_headline_within', {
        defaultValue: 'As-built scan within tolerance',
      });
    default:
      return t('bim.deviation_headline_unknown', {
        defaultValue: 'Scan-vs-design deviation',
      });
  }
}

/**
 * Format one deviation item's RMS for display, e.g. "RMS 4.2 mm / 6 mm".
 *
 * Uses {@link toNum} so the Decimal-as-string wire value is coerced safely
 * (never `.toFixed` on a raw string). Returns null when no RMS was measured so
 * the caller can show "not measured" instead.
 */
export function formatDeviationRms(
  item: Pick<ScanDeviationItem, 'rms_error' | 'tier_tolerance_mm'>,
): string | null {
  if (item.rms_error == null) return null;
  const rms = toNum(item.rms_error);
  const rmsStr = `${round1(rms)} mm`;
  if (item.tier_tolerance_mm == null) return `RMS ${rmsStr}`;
  const tol = toNum(item.tier_tolerance_mm);
  return `RMS ${rmsStr} / ${round1(tol)} mm`;
}

/** Round to at most one decimal place without trailing ".0". */
function round1(n: number): number {
  return Math.round(n * 10) / 10;
}
