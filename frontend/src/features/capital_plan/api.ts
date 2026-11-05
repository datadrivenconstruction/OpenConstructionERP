// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Typed client for the capital plan module, mounted at /api/v1/capital_plan.
// Money arrives as decimal strings; convert with Number() only at the edge.

import { apiGet, apiPost, apiPatch, apiPut, apiDelete, downloadWithAuth } from '@/shared/lib/api';


export type ItemStatus = 'proposed' | 'funded' | 'deferred';

export interface CapitalPlan {
  id: string;
  node_id: string | null;
  name: string;
  currency: string;
  start_year: number;
  horizon_years: number;
}

export interface Envelope {
  id: string;
  plan_id: string;
  year: number;
  amount: string;
  label: string;
}

export interface EnvelopeBody {
  year: number;
  amount: string;
  label: string;
}

export interface Scenario {
  id: string;
  plan_id: string;
  name: string;
  is_baseline: boolean;
  notes: string;
}

export interface CapitalItem {
  id: string;
  scenario_id: string;
  project_id: string | null;
  title: string;
  priority: number;
  start_year: number;
  duration_years: number;
  total_cost: string;
  phasing: string[];
  status: ItemStatus;
  score: number | null;
}

export interface YearRow {
  year: number;
  demand: string;
  envelope: string;
  gap: string;
  cumulative_gap: string;
}

export interface Finding {
  rule_id: string;
  severity: string;
  message: string;
  element_ref: string | null;
  details: Record<string, unknown>;
}

export interface Summary {
  years: number[];
  rows: YearRow[];
  items: { id: string; spend: Record<string, string>; outside_horizon: string }[];
  totals: Record<string, string>;
  unfunded: string[];
  findings: Finding[];
}

export interface Suggestion {
  id: string;
  status: ItemStatus;
  confidence: number;
  reason: string;
  changed: boolean;
}

export interface AutofundResult {
  items: Suggestion[];
  findings: Finding[];
}

export interface CompareResult {
  years: {
    year: number;
    demand_a: string;
    demand_b: string;
    delta_demand: string;
    gap_a: string;
    gap_b: string;
    delta_gap: string;
  }[];
  changed_items: {
    title: string;
    change: 'added' | 'removed' | 'changed';
    status_a?: string | null;
    status_b?: string | null;
    start_year_a?: number | null;
    start_year_b?: number | null;
  }[];
  totals: Record<string, string>;
}

export interface PlanCreateBody {
  name: string;
  currency: string;
  start_year: number;
  horizon_years: number;
  node_id?: string | null;
}

export type ItemPatchBody = Partial<
  Pick<CapitalItem, 'title' | 'priority' | 'start_year' | 'duration_years' | 'status'>
> & { total_cost?: string };

export const capitalPlanApi = {
  listPlans: () => apiGet<{ items: CapitalPlan[]; total: number }>(`/v1/capital_plan/plans/?limit=500`).then((r) => r.items),
  createPlan: (body: PlanCreateBody) => apiPost<CapitalPlan, PlanCreateBody>(`/v1/capital_plan/plans/`, body),
  listEnvelopes: (planId: string) =>
    apiGet<{ items: Envelope[]; total: number }>(`/v1/capital_plan/plans/${planId}/envelopes/?limit=1000`).then((r) => r.items),
  replaceEnvelopes: (planId: string, envelopes: EnvelopeBody[]) =>
    apiPut<Envelope[], { envelopes: EnvelopeBody[] }>(`/v1/capital_plan/plans/${planId}/envelopes/`, { envelopes }),
  listScenarios: (planId: string) =>
    apiGet<{ items: Scenario[]; total: number }>(`/v1/capital_plan/plans/${planId}/scenarios/?limit=500`).then((r) => r.items),
  cloneScenario: (planId: string, scenarioId: string, name?: string) =>
    apiPost<Scenario, { name?: string }>(`/v1/capital_plan/plans/${planId}/scenarios/${scenarioId}/clone/`, { name }),
  deleteScenario: (planId: string, scenarioId: string) =>
    apiDelete(`/v1/capital_plan/plans/${planId}/scenarios/${scenarioId}/`),
  listItems: (scenarioId: string) =>
    apiGet<{ items: CapitalItem[]; total: number }>(`/v1/capital_plan/scenarios/${scenarioId}/items/?limit=5000`).then(
      (r) => r.items,
    ),
  patchItem: (itemId: string, body: ItemPatchBody) =>
    apiPatch<CapitalItem, ItemPatchBody>(`/v1/capital_plan/items/${itemId}/`, body),
  applyStatuses: (scenarioId: string, items: { id: string; status: ItemStatus }[]) =>
    apiPatch<CapitalItem[], { items: { id: string; status: ItemStatus }[] }>(
      `/v1/capital_plan/scenarios/${scenarioId}/items/`,
      { items },
    ),
  importProjects: (planId: string, scenarioId: string) =>
    apiPost<{ created: CapitalItem[]; skipped: number }>(
      `/v1/capital_plan/plans/${planId}/import-projects/?scenario_id=${scenarioId}`,
    ),
  summary: (scenarioId: string) => apiGet<Summary>(`/v1/capital_plan/scenarios/${scenarioId}/summary/`),
  autofund: (scenarioId: string) => apiPost<AutofundResult>(`/v1/capital_plan/scenarios/${scenarioId}/autofund/`),
  compare: (planId: string, a: string, b: string) =>
    apiGet<CompareResult>(`/v1/capital_plan/plans/${planId}/compare/?a=${a}&b=${b}`),
  exportXlsx: (scenarioId: string) =>
    downloadWithAuth(`/api/v1/capital_plan/scenarios/${scenarioId}/export/`, 'capital_plan.xlsx'),
};
