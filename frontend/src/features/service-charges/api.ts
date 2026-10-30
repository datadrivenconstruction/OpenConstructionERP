// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for owners associations, apportionment keys, charge budgets, demands and
 * year-end reconciliation (/v1/service-charges). Money arrives and leaves as decimal strings.
 */
import { API_BASE, apiDelete, apiGet, apiPatch, apiPost, downloadWithAuth } from '@/shared/lib/api';

const BASE = '/v1/service-charges';

export type KeyMethod = 'area' | 'permille' | 'equal' | 'custom';
export type Frequency = 'annual' | 'semiannual' | 'quarterly' | 'monthly';
export type BudgetStatus = 'draft' | 'approved' | 'closed';

export interface Association {
  id: string;
  project_id: string;
  name: string;
  legal_entity_id: string | null;
  registration: Record<string, unknown>;
  currency: string;
  fiscal_year_start_month: number;
  notes: string | null;
}

export interface AssociationCreate {
  project_id: string;
  name: string;
  currency: string;
  fiscal_year_start_month: number;
  registration?: Record<string, unknown>;
}

export interface KeyLine {
  unit_ref: string;
  unit_label: string;
  share: string;
  payer_contact_id: string | null;
}

export interface ApportionmentKey {
  id: string;
  association_id: string;
  name: string;
  method: KeyMethod;
  lines: KeyLine[];
}

export interface BudgetLine {
  id: string;
  category: string;
  description: string;
  amount: string;
  key_id: string;
}

export interface Budget {
  id: string;
  association_id: string;
  year: number;
  status: BudgetStatus;
  demand_frequency: Frequency;
  default_key_id: string | null;
  approved_at: string | null;
  lines: BudgetLine[];
  total: string;
}

export interface Demand {
  id: string;
  budget_id: string;
  unit_ref: string;
  period: number;
  issue_date: string;
  amount: string;
  currency: string;
  invoice_id: string | null;
}

export interface UnitBalance {
  unit_ref: string;
  demanded: string;
  actual_share: string;
  balance: string;
}

export interface Reconciliation {
  id: string;
  budget_id: string;
  status: 'draft' | 'posted';
  actual_by_category: Record<string, string>;
  unit_balances: UnitBalance[];
  unallocated: Record<string, string>;
  sources: { kind: string; id: string; ref: string; currency: string; amount: string }[];
  total_actual: string;
  total_demanded: string;
  posted_invoice_ids: string[];
  posted_credit_ids: string[];
}

export const fetchAssociations = (projectId: string) =>
  apiGet<{ items: Association[]; total: number }>(`${BASE}/?project_id=${projectId}`).then((r) => r.items);
export const createAssociation = (body: AssociationCreate) => apiPost<Association>(`${BASE}/`, body);
export const fetchAssociation = (id: string) => apiGet<Association>(`${BASE}/${id}`);
export const updateAssociation = (id: string, body: Partial<AssociationCreate>) =>
  apiPatch<Association>(`${BASE}/${id}`, body);
export const deleteAssociation = (id: string) => apiDelete(`${BASE}/${id}`);

export const fetchKeys = (associationId: string) => apiGet<ApportionmentKey[]>(`${BASE}/${associationId}/keys`);
export const createKey = (associationId: string, body: { name: string; method: KeyMethod; lines: Omit<KeyLine, 'unit_label'>[] }) =>
  apiPost<ApportionmentKey>(`${BASE}/${associationId}/keys`, body);
export const deleteKey = (keyId: string) => apiDelete(`${BASE}/keys/${keyId}`);

export const fetchBudgets = (associationId: string) => apiGet<Budget[]>(`${BASE}/${associationId}/budgets`);
export const createBudget = (associationId: string, body: { year: number; demand_frequency: Frequency }) =>
  apiPost<Budget>(`${BASE}/${associationId}/budgets`, body);
export const approveBudget = (budgetId: string) => apiPost<Budget>(`${BASE}/budgets/${budgetId}/approve`, {});
export const addBudgetLine = (budgetId: string, body: { category: string; amount: string; key_id: string }) =>
  apiPost<BudgetLine>(`${BASE}/budgets/${budgetId}/lines`, body);
export const deleteBudgetLine = (lineId: string) => apiDelete(`${BASE}/budget-lines/${lineId}`);

export const fetchDemands = (budgetId: string) => apiGet<Demand[]>(`${BASE}/budgets/${budgetId}/demands`);
export const runDemands = (budgetId: string, period: number) =>
  apiPost<{ period: number; created: number; skipped: number; invoice_ids: string[] }>(`${BASE}/demands/run`, {
    budget_id: budgetId,
    period,
  });

export const fetchReconciliation = (budgetId: string) =>
  apiGet<Reconciliation | null>(`${BASE}/budgets/${budgetId}/reconciliation`);
export const computeReconciliation = (budgetId: string) =>
  apiPost<Reconciliation>(`${BASE}/budgets/${budgetId}/reconciliation/compute`, {});
export const postReconciliation = (budgetId: string) =>
  apiPost<Reconciliation>(`${BASE}/budgets/${budgetId}/reconciliation/post`, {});

export const downloadExport = (associationId: string, format: 'csv' | 'json') =>
  downloadWithAuth(`${API_BASE}${BASE}/${associationId}/export?format=${format}`, `service-charges.${format}`);

export const PERIODS: Record<Frequency, number> = { annual: 1, semiannual: 2, quarterly: 4, monthly: 12 };
