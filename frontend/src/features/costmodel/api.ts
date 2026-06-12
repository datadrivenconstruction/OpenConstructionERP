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
  getBudgetLines: (projectId: string) =>
    apiGet<BudgetLine[]>(`/v1/costmodel/projects/${projectId}/5d/budget-lines/`),
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
};
