// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

export interface DashboardData {
  total_budget: number;
  total_committed: number;
  total_actual: number;
  total_forecast: number;
  variance: number;
  variance_pct: number;
  spi: number;
  cpi: number;
  status: string;
  currency: string;
}

export interface SCurvePoint {
  period: string;
  planned: number;
  earned: number;
  actual: number;
}

export interface CashFlowPoint {
  period: string;
  planned_inflow: number;
  planned_outflow: number;
  actual_inflow: number;
  actual_outflow: number;
  cumulative_planned: number;
  cumulative_actual: number;
}

export interface BudgetLine {
  id: string;
  project_id: string;
  boq_position_id: string | null;
  activity_id: string | null;
  category: string;
  description: string;
  planned_amount: number;
  committed_amount: number;
  /**
   * True when committed_amount is this line's share of the purchase orders
   * and contracts on its cost line; the API refuses a typed value then.
   */
  committed_from_documents?: boolean;
  actual_amount: number;
  forecast_amount: number;
  /**
   * EVM earned value (BCWP) for this line. Written automatically from
   * recorded field progress entries; the backend sends it as a
   * Decimal-encoded string, null = no progress recorded yet.
   */
  earned_amount?: number | string | null;
  currency: string;
  period_start: string | null;
  period_end: string | null;
  /**
   * Cost-overrun alert threshold (Gap D): a percentage above planned at which
   * an alert fires. Backend sends it as a Decimal-encoded string; '0' disables.
   */
  overrun_alert_threshold_pct?: string;
  /** ISO timestamp of the last overrun alert sent for this line (null = never). */
  overrun_alerted_at?: string | null;
}

export interface BudgetCategorySummary {
  category: string;
  planned: number;
  committed: number;
  actual: number;
  forecast: number;
  /** planned - forecast, absolute currency (sent by backend). */
  variance: number;
  variance_pct: number;
}

/**
 * Contract exposure for a single cost group: how much of the group budget is
 * already committed to contracts (subcontracts, purchase orders, awarded
 * values), how much is still free to commit, and whether it is overcommitted.
 *
 * IMPORTANT: ``budgeted`` / ``committed`` / ``remaining_to_commit`` are
 * Decimal-encoded STRINGS - format them at the edge, never store as a number.
 * ``commitment_ratio`` is a committed/budget fraction (0.5 = 50%), or null when
 * the group budget is zero or absent. ``remaining_to_commit`` goes negative
 * when the group is overcommitted.
 */
export interface ContractExposureGroup {
  group: string;
  budgeted: string;
  committed: string;
  remaining_to_commit: string;
  commitment_ratio: number | null;
  overcommitted: boolean;
}

/**
 * Project-wide committed-vs-budget contract-exposure rollup.
 *
 * Mirrors the sibling money surfaces (dashboard / EVM): it carries the project
 * base ``currency`` and a ``mixed_currency`` flag (true when the budget lines
 * span more than one currency, so a missing fx rate may have blended the summed
 * totals). Every money field (``total_budgeted`` / ``total_committed`` /
 * ``total_remaining_to_commit``) is a Decimal-encoded STRING;
 * ``total_commitment_ratio`` is a fraction or null.
 */
export interface ContractExposureResponse {
  currency: string;
  mixed_currency: boolean;
  total_budgeted: string;
  total_committed: string;
  total_remaining_to_commit: string;
  total_commitment_ratio: number | null;
  overcommitted: boolean;
  overcommitted_group_count: number;
  groups: ContractExposureGroup[];
}

export interface Snapshot {
  id: string;
  project_id: string;
  period: string;
  planned_cost: number;
  earned_value: number;
  actual_cost: number;
  forecast_eac: number;
  spi: number;
  cpi: number;
  notes: string;
  created_at: string;
}

export interface EVMData {
  bac: number;
  pv: number;
  ev: number;
  ac: number;
  sv: number;
  cv: number;
  spi: number;
  cpi: number;
  eac: number;
  etc: number;
  vac: number;
  tcpi: number;
  time_elapsed_pct: number;
  schedule_progress_pct: number;
  status: string;
  /**
   * True when SPI was clamped to a safe range because the PV proxy is
   * unreliable (e.g. project not started yet). Treat SPI as indicative only.
   */
  spi_capped: boolean;
}

export interface WhatIfAdjustments {
  name: string;
  material_cost_pct: number;
  labor_cost_pct: number;
  duration_pct: number;
}

export interface WhatIfResult {
  scenario_name: string;
  original_bac: number;
  adjusted_bac: number;
  original_eac: number;
  adjusted_eac: number;
  delta: number;
  delta_pct: number;
  adjustments_applied: Record<string, number>;
  snapshot_id: string | null;
}

/* ── Cost Spine ────────────────────────────────────────────────────────── */

/**
 * A control account in the project cost spine (tree node).
 *
 * Control accounts form the hierarchical backbone that cost lines hang off.
 * Returned tree-ordered by the backend (parent before children, then
 * ``sort_order``) so the UI can render the tree without re-sorting.
 */
export interface ControlAccount {
  id: string;
  project_id: string;
  parent_id: string | null;
  code: string;
  name: string;
  classification_standard: string;
  status: string;
  sort_order: number;
}

/**
 * A single cost line in the spine.
 *
 * Estimate money fields (``estimate_unit_rate`` / ``estimate_amount``) are
 * emitted by the backend as Decimal-encoded strings to preserve precision;
 * keep them typed as ``string`` and only coerce to a number at the moment of
 * formatting. ``estimate_quantity`` is likewise a Decimal string.
 */
export interface CostLine {
  id: string;
  project_id: string;
  control_account_id: string | null;
  code: string;
  description: string;
  unit: string;
  source: string;
  boq_position_id: string | null;
  currency: string;
  estimate_quantity: string;
  estimate_unit_rate: string;
  estimate_amount: string;
  status: string;
}

/**
 * Rolled-up view of one cost line: its estimate next to budget, commitment,
 * contract and actual figures aggregated from every linked downstream record.
 *
 * IMPORTANT: every money field is a Decimal-encoded STRING (not a number).
 * The backend rolls these up with exact decimal arithmetic; rounding them
 * through a JS ``number`` here would silently corrupt totals. Format at the
 * edge, never store as a number.
 */
export interface CostLineRollup {
  cost_line_id: string;
  code: string;
  control_account_id: string | null;
  description: string;
  currency: string;
  estimate_amount: string;
  budget_planned: string;
  budget_committed: string;
  budget_actual: string;
  po_committed: string;
  contracted_value: string;
  claimed_to_date: string;
  variance_estimate_vs_budget: string;
  links: {
    boq_position_ids: string[];
    budget_line_ids: string[];
    po_item_ids: string[];
    contract_line_ids: string[];
    rfq_ids: string[];
  };
}

/**
 * One bill position with everything the site has recorded against it.
 *
 * The estimator's side of the spine rollup above: keyed by BOQ position rather
 * than by cost line, and carrying two physical facts the cost line does not
 * hold, percent installed and material issued from the store.
 *
 * Every numeric field is the project-wide Decimal-as-string contract. Two of
 * the nulls here are load-bearing and must not be collapsed on the way to the
 * screen:
 *
 * - `installed_percent` is null when the crew has NEVER reported on this
 *   position, which is a different fact from reporting zero. Note that
 *   `installed_amount` is derived from it server side and reads "0.00" in that
 *   same case, so it is only meaningful when the percent is non-null.
 * - `on_cost_spine` false means the position carries no cost line, so nothing
 *   COULD have been attributed to it in money. True with a zero means nothing
 *   HAS been. The money fields cannot tell those apart on their own.
 *
 * `consumed_quantity` is in the position's own unit and is comparable with
 * `estimate_quantity` only when the store issues in that same unit, which is
 * why the raw numbers and the unit travel together and no ratio is computed.
 */
export interface PositionActualsRow {
  boq_position_id: string;
  ordinal: string;
  description: string;
  unit: string;
  cost_line_id: string | null;
  cost_line_code: string;
  on_cost_spine: boolean;

  estimate_quantity: string;
  /** Deliberately not quantised to the currency minor unit server side: a rate
   *  may carry four decimals and rounding it before it meets a quantity is the
   *  bug that precision guards against. */
  estimate_unit_rate: string;
  estimate_amount: string;

  budget_planned: string;
  budget_actual: string;
  committed_amount: string;
  contracted_amount: string;
  claimed_amount: string;
  /** Estimate minus committed, reported SIGNED. Negative means more has been
   *  ordered against the item than was estimated for it, a finding rather than
   *  an error, so it is never floored at zero. */
  uncommitted_amount: string;

  installed_percent: string | null;
  installed_amount: string;

  consumed_quantity: string;
  consumed_amount: string;
}

/**
 * Position actuals for a project.
 *
 * `currency` is the project base currency and is legitimately the empty string
 * when the project has none. That is an honest unknown and must be rendered as
 * one; defaulting it to a currency prints a wrong unit on every amount.
 */
export interface PositionActualsResponse {
  currency: string;
  rows: PositionActualsRow[];
  totals: Record<string, string>;
  positions_off_spine: number;
}

/** Aggregate totals across the whole spine (same Decimal-string contract). */
export interface SpineRollupTotals {
  estimate_amount: string;
  budget_planned: string;
  budget_committed: string;
  budget_actual: string;
  po_committed: string;
  contracted_value: string;
  claimed_to_date: string;
  variance_estimate_vs_budget: string;
}

/**
 * Whole-spine rollup: the control-account tree, every cost line rollup, and
 * project-level totals.
 *
 * ``mixed_currency`` is true when the spine contains cost lines in more than
 * one currency, in which case the summed totals are not meaningful and the UI
 * must warn rather than present a blended figure.
 */
export interface SpineRollup {
  currency: string;
  mixed_currency: boolean;
  accounts: ControlAccount[];
  lines: CostLineRollup[];
  totals: SpineRollupTotals;
}

/** Result of generating spine lines from a BOQ (created-record counts). */
export interface SpineGenerationResult {
  accounts_created: number;
  lines_created: number;
}

/** Query parameters accepted by the cost-line listing endpoint. */
export interface SpineLinesParams {
  control_account_id?: string;
  status?: string;
  offset?: number;
  limit?: number;
}

/** Body for linking a cost line to a downstream record. */
export interface SpineLinkBody {
  target_type: string;
  target_id: string;
}

export const costModelApi = {
  getDashboard: (projectId: string) =>
    apiGet<DashboardData>(`/v1/costmodel/projects/${projectId}/5d/dashboard/`),
  getSCurve: (projectId: string) =>
    apiGet<{ periods: SCurvePoint[] }>(`/v1/costmodel/projects/${projectId}/5d/s-curve/`),
  getCashFlow: (projectId: string) =>
    apiGet<{ periods: CashFlowPoint[] }>(`/v1/costmodel/projects/${projectId}/5d/cash-flow/`),
  getBudgetSummary: (projectId: string) =>
    apiGet<{ categories: BudgetCategorySummary[] }>(`/v1/costmodel/projects/${projectId}/5d/budget/`),
  getContractExposure: (projectId: string) =>
    apiGet<ContractExposureResponse>(
      `/v1/costmodel/projects/${projectId}/5d/contract-exposure/`,
    ),
  getBudgetLines: (projectId: string) =>
    apiGet<BudgetLine[]>(`/v1/costmodel/projects/${projectId}/5d/budget-lines/?limit=1000`),
  /**
   * Record field progress for the BOQ position behind a budget line. The
   * backend progress module turns the percent into EVM earned value on the
   * same line (BCWP = position total x percent / 100).
   */
  recordProgress: (data: {
    project_id: string;
    boq_position_id: string;
    percent_complete: number;
    period_label: string;
  }) => apiPost('/v1/progress/entries/', data),
  createBudgetLine: (projectId: string, data: Partial<BudgetLine>) =>
    apiPost<BudgetLine>(`/v1/costmodel/projects/${projectId}/5d/budget-lines/`, data),
  updateBudgetLine: (id: string, data: Partial<BudgetLine>) =>
    apiPatch<BudgetLine>(`/v1/costmodel/5d/budget-lines/${id}`, data),
  /**
   * Arm (or disable) the cost-overrun alert threshold on a budget line (Gap D).
   * ``threshold`` is a percentage in [0, 100]; 0 disables alerting. The value
   * travels as a query parameter to match the backend endpoint contract.
   */
  setOverrunAlertThreshold: (id: string, threshold: number) =>
    apiPatch<BudgetLine>(
      `/v1/costmodel/5d/budget-lines/${id}/overrun-alert-threshold?threshold=${encodeURIComponent(
        String(threshold),
      )}`,
      {},
    ),
  generateBudgetFromBoq: (projectId: string, boqId: string) =>
    apiPost(`/v1/costmodel/projects/${projectId}/5d/generate-budget/`, { boq_id: boqId }),
  createSnapshot: (projectId: string, data: { period: string; notes?: string }) =>
    apiPost<Snapshot>(`/v1/costmodel/projects/${projectId}/5d/snapshots/`, data),
  getSnapshots: (projectId: string) =>
    apiGet<Snapshot[]>(`/v1/costmodel/projects/${projectId}/5d/snapshots/`),
  deleteSnapshot: (projectId: string, snapshotId: string) =>
    apiDelete(`/v1/costmodel/projects/${projectId}/5d/snapshots/${snapshotId}`),
  generateCashFlow: (projectId: string) =>
    apiPost(`/v1/costmodel/projects/${projectId}/5d/generate-cash-flow/`, {}),
  getEVM: (projectId: string) =>
    apiGet<EVMData>(`/v1/costmodel/projects/${projectId}/5d/evm/`),
  createWhatIfScenario: (projectId: string, data: WhatIfAdjustments) =>
    apiPost<WhatIfResult>(`/v1/costmodel/projects/${projectId}/5d/what-if/`, data),

  /* ── Cost Spine ──────────────────────────────────────────────────────── */

  getSpineAccounts: (projectId: string) =>
    apiGet<ControlAccount[]>(`/v1/costmodel/projects/${projectId}/spine/accounts/`),
  getSpineLines: (projectId: string, params?: SpineLinesParams) => {
    const qs = new URLSearchParams();
    if (params?.control_account_id) qs.set('control_account_id', params.control_account_id);
    if (params?.status) qs.set('status', params.status);
    if (params?.offset !== undefined) qs.set('offset', String(params.offset));
    if (params?.limit !== undefined) qs.set('limit', String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return apiGet<CostLine[]>(`/v1/costmodel/projects/${projectId}/spine/lines/${suffix}`);
  },
  generateSpine: (projectId: string, boqId?: string) =>
    apiPost<SpineGenerationResult>(
      `/v1/costmodel/projects/${projectId}/spine/generate-from-boq/`,
      boqId ? { boq_id: boqId } : {},
    ),
  getSpineRollup: (projectId: string) =>
    apiGet<SpineRollup>(`/v1/costmodel/projects/${projectId}/spine/rollup/`),
  getLineRollup: (lineId: string) =>
    apiGet<CostLineRollup>(`/v1/costmodel/spine/lines/${lineId}/rollup/`),
  linkSpineTarget: (lineId: string, body: SpineLinkBody) =>
    apiPost<CostLineRollup>(`/v1/costmodel/spine/lines/${lineId}/link/`, body),

  /**
   * What has actually happened against one bill position.
   *
   * Narrowed with `position_id` rather than filtered client side: the endpoint
   * applies the narrowing BEFORE its aggregates run, so a drawer opened on a
   * single position does not pay for the whole project's rollup.
   */
  getPositionActuals: (projectId: string, positionId: string) =>
    apiGet<PositionActualsResponse>(
      `/v1/costmodel/projects/${projectId}/spine/position-actuals/?position_id=${encodeURIComponent(positionId)}`,
    ),
};
