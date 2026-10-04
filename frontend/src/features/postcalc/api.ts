// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Post-calculation (Nachkalkulation).
 *
 * One read-only endpoint, mounted at /api/v1/postcalc, that reconciles a
 * project's estimate against its site actuals: the labour hours the estimate
 * budgeted against the hours really booked, and the material money it allowed
 * against what the store really consumed, both measured for the quantity that
 * was actually installed.
 *
 * Every number crosses the wire as a canonical decimal STRING, never a float,
 * and every optional figure is `null` when the platform has no source for it.
 * That `null` is load-bearing and must never be rendered as a zero: labour and
 * plant are priced from approved timesheets, material from the site inventory
 * ledger, and subcontract, equipment and other from nothing at all today.
 */

import { apiGet, apiPut, downloadWithAuth } from '@/shared/lib/api';

/* -- Types ----------------------------------------------------------------- */

/** Per-line productivity verdict. The stable tokens the model emits. */
export type LineStatus =
  | 'on_plan'
  | 'under_productive'
  | 'over_productive'
  | 'no_baseline'
  | 'no_actuals'
  | 'no_progress';

/** One BoQ line, estimate against site. */
export interface ProductivityLine {
  ref: string;
  description: string;
  unit: string;
  currency: string;
  planned_quantity: string;
  actual_quantity: string;
  progress_pct: string | null;
  planned_hours: string;
  actual_hours: string;
  planned_hours_per_unit: string | null;
  actual_hours_per_unit: string | null;
  earned_hours: string | null;
  hours_variance: string | null;
  productivity_factor: string | null;
  variance_pct: string | null;
  planned_labour_cost: string;
  earned_labour_cost: string | null;
  actual_labour_cost: string | null;
  labour_cost_variance: string | null;
  labour_cost_variance_earned: string | null;
  planned_material_cost: string;
  earned_material_cost: string | null;
  /** `null` means the site recorded no priced consumption for the line, which
   *  is not the same as the line having used no material. */
  actual_material_cost: string | null;
  material_cost_variance: string | null;
  material_cost_variance_earned: string | null;
  status: LineStatus | string;
  status_i18n_key: string;
}

/** One resource category rolled up across the project. */
export interface ResourceRollup {
  kind: string;
  kind_i18n_key: string;
  label: string;
  is_hour_based: boolean;
  planned_hours: string;
  earned_hours: string;
  actual_hours: string;
  productivity_factor: string | null;
  variance_pct: string | null;
  planned_cost: string;
  /** Earned over every line the estimate priced for this category. Pairs with
   *  `planned_cost`. Never subtract `actual_cost` from this one. */
  earned_cost: string;
  /** Earned over the lines whose actual is known, and the only earned figure
   *  that pairs with `actual_cost`. `null` when nothing prices the category. */
  earned_cost_compared: string | null;
  /** `null` where no actuals source can price the category. */
  actual_cost: string | null;
  cost_variance: string | null;
  cost_variance_earned: string | null;
  status: string;
}

/** A norm the site achieved, offered back to estimating. Never auto-applied. */
export interface FeedbackFactor {
  ref: string;
  description: string;
  unit: string;
  current_hours_per_unit: string;
  observed_hours_per_unit: string;
  suggested_hours_per_unit: string;
  productivity_factor: string;
  variance_pct: string;
  observed_quantity: string;
  confidence: string;
  recommendation: string;
}

export interface ProductivityReport {
  currency: string;
  total_planned_hours: string;
  total_earned_hours: string;
  total_actual_hours: string;
  overall_productivity_factor: string | null;
  overall_variance_pct: string | null;
  total_planned_labour_cost: string;
  /** Earned over every baselined line. Read against the planned total. */
  total_earned_labour_cost: string;
  /** Earned over the lines with a known actual, and the only figure the actual
   *  total may be subtracted from. `null` when no line is priced. */
  total_earned_labour_cost_compared: string | null;
  total_actual_labour_cost: string | null;
  total_planned_material_cost: string;
  total_earned_material_cost: string;
  total_earned_material_cost_compared: string | null;
  total_actual_material_cost: string | null;
  /** How many lines the field could price. A total built from three of forty
   *  lines is a different statement from one built from forty, and the
   *  difference is invisible in the total itself. */
  labour_priced_line_count: number;
  material_priced_line_count: number;
  total_planned_value: string;
  line_count: number;
  compared_line_count: number;
  status_counts: Record<string, number>;
  lines: ProductivityLine[];
  resources: ResourceRollup[];
  feedback_factors: FeedbackFactor[];
}

/* -- Endpoints ------------------------------------------------------------- */

function path(projectId: string): string {
  return `/v1/postcalc/projects/${projectId}/productivity`;
}

/**
 * Load the live report for a project.
 *
 * @param projectId - Project to reconcile.
 * @param tolerance - On-plan band as a fraction, e.g. 0.05 for five percent.
 */
export async function fetchProductivity(
  projectId: string,
  tolerance?: number,
): Promise<ProductivityReport> {
  const params = new URLSearchParams({ format: 'json' });
  if (tolerance !== undefined) params.set('tolerance', String(tolerance));
  return apiGet<ProductivityReport>(`${path(projectId)}?${params.toString()}`);
}

/** Download the same numbers as an auditable Markdown document. */
export async function downloadProductivityMarkdown(
  projectId: string,
  tolerance?: number,
): Promise<void> {
  const params = new URLSearchParams({ format: 'markdown' });
  if (tolerance !== undefined) params.set('tolerance', String(tolerance));
  return downloadWithAuth(
    `/api${path(projectId)}?${params.toString()}`,
    `postcalc-${projectId}.md`,
  );
}

/* -- Quantity check -------------------------------------------------------- */

/** Where a line's measured quantity came from. */
export type MeasuredSource = 'measurement_sheet' | 'gaeb_x31';

/** Contract against measured, decided exactly (the highlight band is the view's). */
export type QuantityStatus = 'over' | 'under' | 'matches' | 'not_measured';

/** One bill position: contract quantity against measured quantity. */
export interface QuantityCheckLine {
  position_id: string;
  ordinal: string;
  description: string;
  unit: string;
  /** `null` for a position added to the bill after the baseline. */
  contract_quantity: string | null;
  contract_unit_rate: string | null;
  contract_value: string | null;
  /** `null` when the site has not measured the position (or only the take-off exists). */
  measured_quantity: string | null;
  measured_source: MeasuredSource | null;
  difference: string | null;
  /** `null` when the contract quantity is zero or unknown: no ratio exists. */
  difference_pct: string | null;
  /** Difference at the contract unit rate, net of bill markups, in the bill currency. */
  cost_effect: string | null;
  status: QuantityStatus;
  in_baseline: boolean;
  in_bill: boolean;
  /** The sheet is the one the bill was let with: the estimating take-off. */
  sheet_unchanged_since_baseline: boolean;
  /** No baseline, and the bill quantity equals a sheet the editor saved into it. */
  contract_quantity_may_be_measured: boolean;
}

export interface QuantityCheckTotals {
  line_count: number;
  measured_count: number;
  not_measured_count: number;
  over_count: number;
  under_count: number;
  matches_count: number;
  contract_value: string;
  measured_contract_value: string;
  cost_effect_over: string;
  cost_effect_under: string;
  cost_effect_net: string;
}

export interface QuantityCheckBill {
  id: string;
  name: string;
  is_locked: boolean;
  currency: string;
}

export interface QuantityCheckSnapshot {
  id: string;
  name: string;
  created_at: string | null;
  position_count: number | null;
}

export interface QuantityCheckBaseline {
  kind: 'snapshot' | 'current';
  snapshot_id: string | null;
  name: string | null;
  created_at: string | null;
  designated: boolean;
  designated_reason?: string | null;
}

export interface QuantityCheckReport {
  project_id: string;
  country_code: string;
  boqs: QuantityCheckBill[];
  boq_id: string | null;
  boq_name?: string;
  currency?: string;
  is_locked?: boolean;
  baseline?: QuantityCheckBaseline;
  designated_snapshot_id?: string | null;
  snapshots?: QuantityCheckSnapshot[];
  warnings?: string[];
  lines: QuantityCheckLine[];
  totals: QuantityCheckTotals;
}

/**
 * Load the quantity check of one bill.
 *
 * @param boqId - The bill; the project's first bill when omitted.
 * @param snapshotId - Read the contract side from this snapshot instead of the
 *   bill's designated baseline, for this view only.
 */
export async function fetchQuantityCheck(
  projectId: string,
  boqId?: string,
  snapshotId?: string,
): Promise<QuantityCheckReport> {
  const params = new URLSearchParams();
  if (boqId) params.set('boq_id', boqId);
  if (snapshotId) params.set('snapshot_id', snapshotId);
  const query = params.toString();
  return apiGet<QuantityCheckReport>(`/v1/postcalc/projects/${projectId}/quantity-check${query ? `?${query}` : ''}`);
}

/** Name the bill's baseline snapshot, freeze the bill as it stands, or clear it. */
export async function setQuantityBaseline(
  projectId: string,
  body: { boq_id: string; snapshot_id?: string | null; freeze?: boolean },
): Promise<QuantityCheckReport> {
  return apiPut<QuantityCheckReport, typeof body>(`/v1/postcalc/projects/${projectId}/quantity-check/baseline`, body);
}
