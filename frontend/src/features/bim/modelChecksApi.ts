// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Typed client for the automated model-checking endpoints (validation module).
 *
 * These two endpoints already exist on the backend; the Model Review page is
 * the first surface to call them. They are model-scoped, so the client lives
 * here in `features/bim` next to the panel that consumes it.
 *
 *   POST /v1/validation/check-bim-model            — run the per-element rule
 *       engine over a model and persist + return a ValidationReport whose
 *       `results` carry an `element_id` back-reference per finding.
 *   GET  /v1/validation/bim-scorecard/{model_id}   — read-only maturity
 *       scorecard (facet sub-scores + grade) plus a version-over-version score
 *       trend, computed live from the model's current elements and its
 *       persisted report history. Writes nothing.
 *
 * NB: `score` (and the trend `*_score` fields the report persists) is a
 * decimal serialised as a string, mirroring the money/decimal convention used
 * across the platform — parse with `Number(...)` and guard for `null`.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

/* ── check-bim-model ────────────────────────────────────────────────────── */

/** One finding row inside a BIM check report. Mirrors the entries persisted
 *  by `BIMValidationService` — each carries `element_id` so the UI can map a
 *  failure back to the offending element and focus it in the viewer. */
export interface BIMCheckResultItem {
  rule_id: string;
  rule_name: string;
  /** `error` | `warning` | `info` (the `_truncated` sentinel uses `info`). */
  severity: 'error' | 'warning' | 'info' | string;
  status: string;
  passed: boolean;
  message: string;
  /** BIMElement DB id (== the viewer's skeleton element id). `null` on the
   *  synthetic `_truncated` / engine-error rows that carry no element. */
  element_id: string | null;
  element_name: string | null;
  element_type: string | null;
  /** Equal to `element_id` for real findings; kept for parity with the core
   *  validation report shape. */
  element_ref: string | null;
  details?: Record<string, unknown> | null;
  /** True on rows that record a rule crash rather than a compliance finding. */
  is_engine_error?: boolean;
}

/** Metadata blob folded onto a BIM check report. */
export interface BIMCheckReportMetadata {
  duration_ms?: number;
  model_id?: string;
  model_name?: string;
  element_count?: number;
  rule_ids?: string[];
  ids_rule_set?: string | null;
  truncated?: boolean;
  /** Info-severity findings are counted here, not in a top-level field. */
  info_count?: number;
  failed_check_count?: number;
}

/** Response of POST /v1/validation/check-bim-model (a ValidationReport). */
export interface BIMCheckReport {
  id: string;
  project_id: string;
  target_type: string;
  target_id: string;
  rule_set: string;
  /** `passed` | `warnings` | `errors` | `info` | `skipped`. */
  status: 'passed' | 'warnings' | 'errors' | 'info' | 'skipped' | string;
  /** Decimal quality score as a string ("0.8734"), or `null` when skipped. */
  score: string | null;
  /** Total (rule, element) checks executed. */
  total_rules: number;
  passed_count: number;
  error_count: number;
  warning_count: number;
  results: BIMCheckResultItem[];
  created_by?: string | null;
  created_at: string | null;
  metadata: BIMCheckReportMetadata;
}

/**
 * Run the automated per-element checks over a model.
 *
 * `ruleIds` is optional — omit it to run the full enabled universal rule set
 * (the common case). Flagged `longRunning` because a large model runs every
 * rule against every element server-side.
 */
export async function checkBimModel(
  modelId: string,
  ruleIds?: string[] | null,
): Promise<BIMCheckReport> {
  return apiPost<BIMCheckReport, { model_id: string; rule_ids?: string[] }>(
    '/v1/validation/check-bim-model',
    { model_id: modelId, ...(ruleIds && ruleIds.length > 0 ? { rule_ids: ruleIds } : {}) },
    { longRunning: true },
  );
}

/* ── bim-scorecard ──────────────────────────────────────────────────────── */

/** One maturity facet: a named sub-score with a drill-down of flagged ids. */
export interface BIMScorecardFacet {
  facet_id: string;
  name: string;
  /** 0.0-1.0, or `null` when the facet had no signal to assess. */
  score: number | null;
  grade: string;
  weight: number;
  applicable: boolean;
  covered: number;
  total: number;
  summary: string;
  details: Record<string, unknown>;
  /** BIMElement ids this facet flagged (bounded). */
  element_refs: string[];
}

/** Composite maturity scorecard for one model. */
export interface BIMScorecard {
  model_id: string | null;
  model_name: string | null;
  element_count: number;
  overall_score: number | null;
  overall_grade: string;
  status: string;
  facets: BIMScorecardFacet[];
  element_findings: Record<string, string[]>;
  generated_ms: number;
}

/** One point in the model's validation-score history. */
export interface BIMScorecardTrendPoint {
  report_id: string | null;
  created_at: string | null;
  score: number | null;
  status: string;
  grade: string;
  run: number;
  element_count: number | null;
  rule_set: string | null;
}

/** Ordered score series with an overall direction. */
export interface BIMScorecardTrend {
  target_type: string;
  target_id: string | null;
  /** `improving` | `regressing` | `flat` | `insufficient`. */
  direction: string;
  first_score: number | null;
  latest_score: number | null;
  delta: number | null;
  point_count: number;
  points: BIMScorecardTrendPoint[];
}

/** Response of GET /v1/validation/bim-scorecard/{model_id}. */
export interface BIMScorecardResponse {
  model: {
    id: string;
    name: string;
    project_id: string;
    version?: number | string | null;
    element_count: number;
  };
  scorecard: BIMScorecard;
  /** Present when `include_trend` (the default) was requested. */
  trend?: BIMScorecardTrend;
}

/** Read the maturity scorecard (facets + grade + trend) for a model. */
export async function fetchBimScorecard(modelId: string): Promise<BIMScorecardResponse> {
  return apiGet<BIMScorecardResponse>(
    `/v1/validation/bim-scorecard/${encodeURIComponent(modelId)}`,
  );
}
