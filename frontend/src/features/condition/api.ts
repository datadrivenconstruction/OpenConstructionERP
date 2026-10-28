// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for condition ratings and the maintenance plan (/v1/condition).
 * Money and quantities arrive as decimal strings.
 */
import type { Page } from '@/shared/lib/apiHelpers';
import { API_BASE, apiDelete, apiGet, apiPatch, apiPost, downloadWithAuth } from '@/shared/lib/api';

const BASE = '/v1/condition';

export type AssetKind = 'bim_element' | 'plant_item' | 'element';
export type ActionType = 'inspect' | 'maintain' | 'repair' | 'replace';
export type ActionStatus = 'proposed' | 'approved' | 'done' | 'rejected';

export interface ScaleLevel {
  level: number;
  label: string;
  label_key?: string | null;
  description?: string | null;
  color?: string | null;
  action?: { type: ActionType; label?: string; within_years?: number; interval_years?: number; priority?: number } | null;
}

export interface ConditionScale {
  key: string;
  name: string;
  description?: string | null;
  action_threshold: number;
  levels: ScaleLevel[];
  source: 'builtin' | 'pack' | 'custom';
  pack_slug?: string | null;
  id?: string | null;
}

export interface Assessment {
  id: string;
  project_id: string;
  inspection_id: string | null;
  asset_kind: AssetKind;
  asset_ref: string | null;
  element_name: string;
  element_code: string | null;
  area: string | null;
  scale_key: string;
  rating: number;
  suggested_rating: number | null;
  suggestion_confidence: number | null;
  severity: number | null;
  extent_pct: number | null;
  intensity: number | null;
  defect_description: string | null;
  recommended_action: string | null;
  quantity: string | null;
  unit: string | null;
  unit_cost: string | null;
  currency: string | null;
  assessed_at: string | null;
  assessed_by: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssessmentCreate {
  project_id: string;
  inspection_id?: string | null;
  asset_kind?: AssetKind;
  asset_ref?: string | null;
  element_name: string;
  element_code?: string | null;
  area?: string | null;
  scale_key?: string;
  rating: number;
  severity?: number | null;
  extent_pct?: number | null;
  intensity?: number | null;
  defect_description?: string | null;
  recommended_action?: string | null;
  quantity?: string | null;
  unit?: string | null;
  unit_cost?: string | null;
  currency?: string | null;
  assessed_at?: string | null;
  notes?: string | null;
}

export interface MaintenanceAction {
  id: string;
  project_id: string;
  assessment_id: string | null;
  asset_kind: AssetKind;
  asset_ref: string | null;
  element_name: string;
  area: string | null;
  action_type: ActionType;
  description: string;
  first_year: number;
  interval_years: number | null;
  quantity: string | null;
  unit: string | null;
  unit_cost: string | null;
  currency: string | null;
  priority: number;
  status: ActionStatus;
  source: 'derived' | 'manual';
  confidence: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ActionCreate {
  project_id: string;
  element_name: string;
  action_type: ActionType;
  first_year: number;
  interval_years?: number | null;
  asset_ref?: string | null;
  area?: string | null;
  description?: string;
  quantity?: string | null;
  unit?: string | null;
  unit_cost?: string | null;
  currency?: string | null;
  priority?: number;
}

export interface PlanItem {
  id: string;
  year: number;
  asset_ref: string | null;
  element_name: string;
  area: string | null;
  action_type: ActionType;
  description: string;
  status: ActionStatus;
  priority: number;
  cost: string;
  cost_inflated: string;
  currency: string | null;
}

export interface MaintenancePlan {
  start_year: number;
  horizon_years: number;
  inflation_rate: string;
  discount_rate: string;
  inflation_source: 'explicit' | 'price_index' | 'none';
  currencies: string[];
  years: { year: number; cost: string; cost_inflated: string; items: PlanItem[] }[];
  totals: {
    cost: string;
    cost_inflated: string;
    present_value: string;
    annual_equivalent: string;
    unpriced_actions: number;
  };
  by_asset: Record<string, string>;
}

export interface PlanQuery {
  start_year?: number;
  horizon_years?: number;
  inflation_rate?: string;
  index_series_id?: string;
  discount_rate?: string;
  include_proposed?: boolean;
}

export interface RuleFinding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

function planParams(projectId: string, q: PlanQuery): string {
  const p = new URLSearchParams({ project_id: projectId });
  if (q.start_year) p.set('start_year', String(q.start_year));
  if (q.horizon_years) p.set('horizon_years', String(q.horizon_years));
  if (q.inflation_rate !== undefined && q.inflation_rate !== '') p.set('inflation_rate', q.inflation_rate);
  if (q.index_series_id) p.set('index_series_id', q.index_series_id);
  if (q.discount_rate !== undefined && q.discount_rate !== '') p.set('discount_rate', q.discount_rate);
  if (q.include_proposed) p.set('include_proposed', 'true');
  return p.toString();
}

export const fetchScales = (projectId: string) =>
  apiGet<Page<ConditionScale>>(`${BASE}/scales?project_id=${projectId}`).then((page) => page.items);

export const fetchAssessments = (projectId: string, filters: { inspection_id?: string } = {}) => {
  const p = new URLSearchParams({ project_id: projectId });
  if (filters.inspection_id) p.set('inspection_id', filters.inspection_id);
  return apiGet<Page<Assessment>>(`${BASE}/assessments?${p.toString()}`).then((page) => page.items);
};

export const createAssessment = (payload: AssessmentCreate) => apiPost<Assessment>(`${BASE}/assessments`, payload);

export const deleteAssessment = (id: string) => apiDelete(`${BASE}/assessments/${id}`);

export const suggestRating = (payload: {
  project_id?: string;
  scale_key: string;
  severity?: number | null;
  extent_pct?: number | null;
  intensity?: number | null;
}) => apiPost<{ rating: number | null; confidence: number; level: ScaleLevel | null }>(`${BASE}/suggest-rating`, payload);

export const fetchActions = (projectId: string) =>
  apiGet<Page<MaintenanceAction>>(`${BASE}/actions?project_id=${projectId}`).then((page) => page.items);

export const createAction = (payload: ActionCreate) => apiPost<MaintenanceAction>(`${BASE}/actions`, payload);

export const updateAction = (id: string, patch: Partial<Pick<MaintenanceAction, 'status' | 'unit_cost' | 'first_year' | 'interval_years' | 'quantity'>>) =>
  apiPatch<MaintenanceAction>(`${BASE}/actions/${id}`, patch);

export const deleteAction = (id: string) => apiDelete(`${BASE}/actions/${id}`);

export const derivePlan = (projectId: string, baseYear?: number) =>
  apiPost<{ created: number; skipped: number; actions: MaintenanceAction[] }>(
    `${BASE}/plan/derive?project_id=${projectId}`,
    { base_year: baseYear ?? null },
  );

export const fetchPlan = (projectId: string, q: PlanQuery) => apiGet<MaintenancePlan>(`${BASE}/plan?${planParams(projectId, q)}`);

export const downloadPlanCsv = (projectId: string, q: PlanQuery) =>
  downloadWithAuth(`${API_BASE}${BASE}/plan/export?${planParams(projectId, q)}`, `maintenance_plan_${projectId}.csv`);

export const applyPlanToAssets = (projectId: string, q: PlanQuery) =>
  apiPost<{ updated: number; skipped: number; asset_refs: string[] }>(
    `${BASE}/plan/apply-to-assets?${planParams(projectId, { horizon_years: q.horizon_years, inflation_rate: q.inflation_rate, index_series_id: q.index_series_id })}`,
    {},
  );

export const validateCondition = (projectId: string) =>
  apiGet<{ status: 'passed' | 'warnings' | 'errors'; checked: number; results: RuleFinding[] }>(
    `${BASE}/validate?project_id=${projectId}`,
  );
