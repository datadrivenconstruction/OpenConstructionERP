import { apiGet, apiPost, apiPatch } from '@/shared/lib/api';

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
  currency: string;
  period_start: string | null;
  period_end: string | null;
}

export interface BudgetCategorySummary {
  category: string;
  planned: number;
  committed: number;
  actual: number;
  forecast: number;
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
  createBudgetLine: (projectId: string, data: Partial<BudgetLine>) =>
    apiPost<BudgetLine>(`/v1/costmodel/projects/${projectId}/5d/budget-lines/`, data),
  updateBudgetLine: (id: string, data: Partial<BudgetLine>) =>
    apiPatch<BudgetLine>(`/v1/costmodel/5d/budget-lines/${id}/`, data),
  generateBudgetFromBoq: (projectId: string, boqId: string) =>
    apiPost(`/v1/costmodel/projects/${projectId}/5d/generate-budget/`, { boq_id: boqId }),
  createSnapshot: (projectId: string, data: { period: string; notes?: string }) =>
    apiPost<Snapshot>(`/v1/costmodel/projects/${projectId}/5d/snapshots/`, data),
  getSnapshots: (projectId: string) =>
    apiGet<Snapshot[]>(`/v1/costmodel/projects/${projectId}/5d/snapshots/`),
  generateCashFlow: (projectId: string) =>
    apiPost(`/v1/costmodel/projects/${projectId}/5d/generate-cash-flow/`, {}),
  getEVM: (projectId: string) =>
    apiGet<EVMData>(`/v1/costmodel/projects/${projectId}/5d/evm/`),
  createWhatIfScenario: (projectId: string, data: WhatIfAdjustments) =>
    apiPost<WhatIfResult>(`/v1/costmodel/projects/${projectId}/5d/what-if/`, data),
};
