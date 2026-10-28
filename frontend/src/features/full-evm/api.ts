// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Full EVM module.
 *
 * Backed by /api/v1/full-evm/ — see backend/app/modules/full_evm/router.py.
 * The mount prefix is kebab-case; the module directory is not.
 *
 * Two contracts run through this file and they are easy to confuse.
 *
 * **Money is a string.** Every amount is a `decimal.Decimal` server-side and is
 * serialised verbatim, because a budget routed through an IEEE double comes
 * back a different budget. Amounts stay strings here and are parsed only where
 * one is compared or charted — see evmIndicators.ts.
 *
 * **`null` on an index means undefined, never zero.** CPI is EV/AC and is
 * undefined until money has been spent; SPI is EV/PV and is undefined until
 * work has been scheduled; TCPI is undefined once the budget is exactly
 * consumed. The register stores NULL for those and the wire carries `null`. A
 * reader that coerces them to 0 reports a project that has not started as
 * maximally inefficient, which is the single wrong answer this module was
 * written to avoid.
 *
 * Where the backend declares a bare `str` rather than a Literal — `source`,
 * `eac_method`, `eac_method_effective`, `validation_status` — the type here is
 * `string` too, deliberately: a reader must not crash on a value a later
 * version writes. The unions below type what may be *sent*.
 */

import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from '@/shared/lib/api';

/* ── Shared vocabulary ─────────────────────────────────────────────────── */

/**
 * An EAC formula name. `auto` picks the richest computable variant.
 *
 * Mirrors `EAC_METHODS` in backend/app/modules/eac/evm.py, which the full_evm
 * schemas pin themselves to at import time, so this list cannot drift quietly.
 */
export type EacMethod = 'auto' | 'remaining' | 'cpi' | 'combined';

/** Lifecycle state of a baseline. */
export type BaselineStatus = 'draft' | 'approved' | 'superseded' | 'archived';

/** Where a measurement's observations came from. */
export type MeasureSource = 'manual' | 'finance_snapshot' | 'import';

/**
 * The forecast surface accepts one name the register does not: `spi_cpi` is
 * the module's original name for `combined` and is still honoured, so saved
 * job payloads keep working. The canonical name is what gets recorded.
 */
export type ForecastMethod = EacMethod | 'spi_cpi';

/* ── Validation ────────────────────────────────────────────────────────── */

/** One failing rule result, as stored on a baseline or measurement row. */
export interface ValidationFinding {
  rule_id: string;
  severity: string;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
  details: Record<string, unknown>;
}

/**
 * Outcome of running the `full_evm` rule set over a row.
 *
 * `score` is null when nothing was actually checked. It is not 1.0 there, and
 * rendering it as such would report an unchecked baseline as perfect.
 */
export interface ValidationReport {
  status: string;
  score: number | null;
  findings: ValidationFinding[];
}

/* ── Baselines ─────────────────────────────────────────────────────────── */

/** One point on the cumulative planned-value curve, as returned. */
export interface BaselinePeriod {
  id: string;
  ordinal: number;
  period_end: string;
  label: string;
  /** Cumulative to `period_end`, not the amount planned inside the period. */
  planned_value: string;
  planned_quantity: string | null;
}

/** One point on the curve, as submitted. `ordinal` is assigned by the server. */
export interface BaselinePeriodWrite {
  period_end: string;
  label?: string;
  planned_value: string;
  planned_quantity?: string | null;
}

export interface Baseline {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  status: BaselineStatus;
  bac: string;
  currency: string | null;
  /** Decimal places the currency uses; the money rounding step is 10**-minor_units. */
  minor_units: number;
  start_date: string | null;
  finish_date: string | null;
  approved_by: string | null;
  approved_at: string | null;
  validation_status: string;
  validation_findings: ValidationFinding[];
  validation_score: number | null;
  periods: BaselinePeriod[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface BaselineListResponse {
  items: Baseline[];
  total: number;
}

export interface BaselineCreateBody {
  project_id: string;
  name: string;
  description?: string | null;
  bac: string;
  /** ISO 4217, three letters. A label only: no currency is ever assumed. */
  currency?: string | null;
  minor_units?: number;
  start_date?: string | null;
  finish_date?: string | null;
  periods?: BaselinePeriodWrite[];
  metadata?: Record<string, unknown>;
}

/** Every field optional; an omitted field is left untouched. */
export interface BaselineUpdateBody {
  name?: string;
  description?: string | null;
  bac?: string;
  currency?: string | null;
  minor_units?: number;
  start_date?: string | null;
  finish_date?: string | null;
  metadata?: Record<string, unknown>;
}

/* ── Measurements ──────────────────────────────────────────────────────── */

/**
 * A measurement with its full derived metric set.
 *
 * The observations (bac, pv, ev, ac) and the money variances (sv, cv) are
 * always present. Every index and every forecast figure is nullable, and null
 * means the denominator was zero.
 *
 * `eac_method` is what the caller asked for; `eac_method_effective` is what the
 * maths could actually deliver. They differ whenever a named formula's divisor
 * was zero, and keeping both is what stops the register from claiming a
 * cost-trend forecast it never computed.
 */
export interface Measure {
  id: string;
  baseline_id: string;
  project_id: string;
  data_date: string;
  source: string;
  currency: string | null;

  bac: string;
  pv: string;
  ev: string;
  ac: string;
  planned_quantity: string | null;
  actual_quantity: string | null;

  /** EV - PV. Money, always defined. Negative is behind the plan. */
  sv: string;
  /** EV - AC. Money, always defined. Negative is over budget. */
  cv: string;
  spi: string | null;
  cpi: string | null;
  /** EV/BAC as a **fraction**, not a percentage. Null when BAC is zero. */
  percent_complete: string | null;
  /** AC/BAC as a **fraction**, not a percentage. Null when BAC is zero. */
  percent_spent: string | null;

  eac_method: string;
  eac_method_effective: string;
  eac: string | null;
  etc: string | null;
  vac: string | null;
  /** (BAC-EV)/(BAC-AC). Null once the budget is exactly consumed. */
  tcpi_bac: string | null;
  /** (BAC-EV)/(EAC-AC). Null when no further spend is forecast. */
  tcpi_eac: string | null;
  /** Every EAC formula side by side, so the chosen one is auditable. */
  eac_variants: Record<string, string | null>;

  notes: string | null;
  validation_status: string;
  validation_findings: ValidationFinding[];
  validation_score: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface MeasureListResponse {
  items: Measure[];
  total: number;
}

/**
 * Record an EVM measurement for one data date.
 *
 * Omit `pv` and it is read off the baseline curve at `data_date`, which is the
 * whole reason the curve is stored. Supplying it is an explicit override and
 * the rule `full_evm.measure_pv_follows_baseline` reports it as one.
 *
 * Re-posting the same `data_date` updates that row rather than creating a
 * second, contradictory truth for one cutoff.
 */
export interface MeasureCreateBody {
  data_date: string;
  ev: string;
  ac: string;
  pv?: string | null;
  bac?: string | null;
  planned_quantity?: string | null;
  actual_quantity?: string | null;
  eac_method?: EacMethod;
  source?: MeasureSource;
  notes?: string | null;
  metadata?: Record<string, unknown>;
}

/* ── Curves ────────────────────────────────────────────────────────────── */

/**
 * One plotted point: the plan, and what actually happened by that date.
 *
 * A period nobody measured carries nulls rather than zeros, so the actual curve
 * stops where the data stops instead of drawing an unreported month as a month
 * of no progress.
 */
export interface SCurvePoint {
  as_of: string;
  label: string;
  planned_value: string;
  earned_value: string | null;
  actual_cost: string | null;
  /** EAC in force at this date, when a measurement exists. */
  forecast: string | null;
}

export interface BaselineSCurve {
  baseline_id: string;
  project_id: string;
  currency: string | null;
  bac: string;
  points: SCurvePoint[];
}

/* ── Forecasts (the finance-snapshot surface) ──────────────────────────── */

/**
 * A forecast row derived from a finance EVM snapshot.
 *
 * Amounts are strings here for a different reason than on the register: this
 * table stores them as text columns, matching the finance `EVMSnapshot` it
 * reads from. `tcpi` carries the legacy literal `"inf"` when the budget is
 * exactly consumed with work still outstanding — an unbounded TCPI, not a
 * healthy zero.
 */
export interface EvmForecast {
  id: string;
  project_id: string;
  forecast_date: string;
  etc: string;
  eac: string;
  vac: string;
  tcpi: string;
  forecast_method: string;
  confidence_range_low: string | null;
  confidence_range_high: string | null;
  notes: string | null;
  /** null means no alert on this row. Otherwise triggered, snoozed or acknowledged. */
  alert_status: string | null;
  triggered_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface EvmForecastListResponse {
  items: EvmForecast[];
  total: number;
}

/**
 * A finance EVM snapshot as the s-curve-data endpoint re-serves it.
 *
 * The server builds these as loose dicts out of the finance module's own
 * string columns, so every figure here is a string and none of them is
 * guaranteed to parse.
 */
export interface SnapshotPoint {
  date: string;
  pv: string;
  ev: string;
  ac: string;
  bac: string;
}

/** A forecast row as the s-curve-data endpoint re-serves it. */
export interface ForecastPoint {
  date: string;
  eac: string;
  etc: string;
  vac: string;
  tcpi: string;
  method: string;
  confidence_low: string | null;
  confidence_high: string | null;
}

export interface SCurveData {
  project_id: string;
  snapshots: SnapshotPoint[];
  forecasts: ForecastPoint[];
}

/* ── Glossary ──────────────────────────────────────────────────────────── */

export interface MetricGlossaryEntry {
  code: string;
  label: string;
  explanation: string;
}

/** One EAC formula, its algebra, and when it is the right one to read. */
export interface EacMethodEntry {
  name: string;
  formula: string;
  use_when: string;
}

export interface MetricGlossary {
  metrics: MetricGlossaryEntry[];
  eac_methods: EacMethodEntry[];
  supported_methods: string[];
}

/* ── Calls ─────────────────────────────────────────────────────────────── */

const BASE = '/v1/full-evm';

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : '';
}

/* Baselines */

export function listBaselines(params: {
  projectId: string;
  status?: BaselineStatus;
  limit?: number;
  offset?: number;
}): Promise<BaselineListResponse> {
  return apiGet<BaselineListResponse>(
    `${BASE}/baselines/${qs({
      project_id: params.projectId,
      status: params.status,
      limit: params.limit,
      offset: params.offset,
    })}`,
  );
}

/**
 * Create a baseline, optionally with its whole planned-value curve.
 *
 * The rule set runs immediately, so the returned row already carries a real
 * `validation_status` rather than an unchecked "pending".
 */
export function createBaseline(body: BaselineCreateBody): Promise<Baseline> {
  return apiPost<Baseline, BaselineCreateBody>(`${BASE}/baselines/`, body);
}

export function getBaseline(baselineId: string): Promise<Baseline> {
  return apiGet<Baseline>(`${BASE}/baselines/${baselineId}/`);
}

/** Patch a draft baseline. An approved one is superseded, not edited (409). */
export function updateBaseline(baselineId: string, body: BaselineUpdateBody): Promise<Baseline> {
  return apiPatch<Baseline, BaselineUpdateBody>(`${BASE}/baselines/${baselineId}/`, body);
}

/** Delete a non-approved baseline with its curve and measurements. */
export function deleteBaseline(baselineId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/baselines/${baselineId}/`);
}

/**
 * Replace the whole cumulative planned-value curve in one write.
 *
 * Whole-curve replacement rather than per-row edits: the curve's invariants
 * (rising, ending at the budget) are properties of the set, so a row-by-row
 * path would spend most of its life in a state the rules correctly reject.
 *
 * Submission order is kept as sent and the ordinals are renumbered from it. The
 * server does not sort: an out-of-order curve is a real authoring mistake that
 * `full_evm.baseline_periods_ordered` reports.
 */
export function replaceBaselinePeriods(
  baselineId: string,
  periods: BaselinePeriodWrite[],
): Promise<Baseline> {
  return apiPut<Baseline, { periods: BaselinePeriodWrite[] }>(
    `${BASE}/baselines/${baselineId}/periods/`,
    { periods },
  );
}

/** Re-run the rule set over a baseline and store the outcome on the row. */
export function validateBaseline(baselineId: string): Promise<ValidationReport> {
  return apiPost<ValidationReport>(`${BASE}/baselines/${baselineId}/validate/`);
}

/**
 * Approve a baseline, superseding the project's previous approved one.
 *
 * Refused with 409 while the baseline has blocking validation errors: once a
 * curve is the divisor of every future schedule index, an error in it is no
 * longer a work-in-progress state.
 */
export function approveBaseline(baselineId: string): Promise<Baseline> {
  return apiPost<Baseline>(`${BASE}/baselines/${baselineId}/approve/`);
}

/** Plan versus actual for one baseline. */
export function getBaselineSCurve(baselineId: string): Promise<BaselineSCurve> {
  return apiGet<BaselineSCurve>(`${BASE}/baselines/${baselineId}/s-curve/`);
}

/* Measurements */

export function listMeasures(params: {
  baselineId: string;
  limit?: number;
  offset?: number;
}): Promise<MeasureListResponse> {
  return apiGet<MeasureListResponse>(
    `${BASE}/baselines/${params.baselineId}/measures/${qs({
      limit: params.limit,
      offset: params.offset,
    })}`,
  );
}

/** Record (or re-record) a measurement for one data date. */
export function recordMeasure(baselineId: string, body: MeasureCreateBody): Promise<Measure> {
  return apiPost<Measure, MeasureCreateBody>(`${BASE}/baselines/${baselineId}/measures/`, body);
}

export function getMeasure(measureId: string): Promise<Measure> {
  return apiGet<Measure>(`${BASE}/measures/${measureId}/`);
}

export function deleteMeasure(measureId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/measures/${measureId}/`);
}

/* Forecasts */

/**
 * List a project's forecast rows.
 *
 * The project scope is not optional in practice: the endpoint accepts an
 * omitted `project_id` and answers with an empty list rather than dumping every
 * tenant's forecasts, so calling it unscoped is always a wasted round trip.
 */
export function listForecasts(projectId: string): Promise<EvmForecastListResponse> {
  return apiGet<EvmForecastListResponse>(`${BASE}/forecasts/${qs({ project_id: projectId })}`);
}

/**
 * Recompute a forecast from the project's latest finance EVM snapshot.
 *
 * 404 when the project has no snapshot yet. The stored row records both the
 * formula asked for and, under `metadata.effective_method`, the one that could
 * actually be evaluated; they differ whenever a divisor was zero.
 */
export function calculateForecast(projectId: string, method: ForecastMethod): Promise<EvmForecast> {
  return apiPost<EvmForecast, { project_id: string; forecast_method: ForecastMethod }>(
    `${BASE}/forecasts/calculate/`,
    { project_id: projectId, forecast_method: method },
  );
}

/** Forecasts whose alert is still actionable: triggered or snoozed. */
export function listForecastAlerts(projectId: string): Promise<EvmForecastListResponse> {
  return apiGet<EvmForecastListResponse>(`${BASE}/forecasts/alerts/${qs({ project_id: projectId })}`);
}

/** Resolve a triggered or snoozed alert. */
export function acknowledgeForecastAlert(forecastId: string): Promise<EvmForecast> {
  return apiPost<EvmForecast>(`${BASE}/forecasts/${forecastId}/acknowledge/`);
}

/**
 * Defer an alert for a number of hours.
 *
 * The next batch run re-triggers on the same condition, so a snooze quietens
 * the alert without pretending the breach went away.
 */
export function snoozeForecastAlert(forecastId: string, hours: number): Promise<EvmForecast> {
  return apiPost<EvmForecast, { hours: number }>(`${BASE}/forecasts/${forecastId}/snooze/`, {
    hours,
  });
}

/** Finance snapshots and forecast rows together, for the project-level chart. */
export function getSCurveData(projectId: string): Promise<SCurveData> {
  return apiGet<SCurveData>(`${BASE}/s-curve-data/${qs({ project_id: projectId })}`);
}

/* Glossary */

/**
 * Plain-language meaning of every EVM code and EAC formula.
 *
 * Not project-scoped and carries no data. It exists because CPI, TCPI and VAC
 * mean nothing to a reader seeing them for the first time, and a number nobody
 * can interpret is not information.
 */
export function getMetricGlossary(): Promise<MetricGlossary> {
  return apiGet<MetricGlossary>(`${BASE}/glossary/`);
}
