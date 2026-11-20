// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Central purchasing API (mounted at /api/v1/central-purchasing/).
 * Quantities and money travel as decimal strings; the server computes every split.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';

export type Dec = string;
export type BundleKind = 'subcontract' | 'supply';
export type BundleMode = 'per_project_contracts' | 'framework_call_off';
export type BundleStatus = 'draft' | 'published' | 'awarded' | 'cancelled';

export interface Finding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info' | string;
  message: string;
  suggestion?: string | null;
  element_ref?: string | null;
}

export interface DocumentRef {
  type: 'contract' | 'purchase_order' | 'framework_agreement' | string;
  id: string | null;
  code: string;
  status: string;
  project_id: string | null;
}

export interface ShareOut {
  id: string;
  bundle_project_id: string;
  quantity: Dec | null;
  cost_line_id: string | null;
  cost_line_code: string | null;
}

export interface BundleLine {
  id: string;
  order_index: number;
  code: string;
  description: string;
  unit: string;
  quantity: Dec;
  unit_rate: Dec | null;
  cost_code: string | null;
  shares: ShareOut[];
  share_sum: Dec;
}

export interface BundleProject {
  id: string;
  project_id: string;
  name: string;
  project_code: string | null;
  legal_entity_id: string | null;
  legal_entity_name: string | null;
  budget_amount: Dec | null;
  budget_from_lines: Dec | null;
}

export interface SplitRow {
  bundle_project_id: string;
  project_name: string;
  legal_entity_name: string | null;
  gross: Dec;
  discount: Dec;
  net: Dec;
  budget: Dec | null;
  over_budget: boolean;
  budget_delta: Dec | null;
  document: DocumentRef | null;
}

export interface Split {
  method: 'unit_rates' | 'lump_sum';
  gross: Dec;
  net: Dec;
  target: Dec;
  reconciles: boolean;
  rows: SplitRow[];
}

export interface BundleSummary {
  id: string;
  code: string;
  title: string;
  kind: BundleKind;
  mode: BundleMode;
  status: BundleStatus;
  currency: string;
  vendor_name: string;
  project_count: number;
  line_count: number;
  gross: Dec;
  net: Dec;
  errors: number;
  warnings: number;
}

export interface BundleDetail {
  id: string;
  code: string;
  title: string;
  description: string;
  kind: BundleKind;
  mode: BundleMode;
  status: BundleStatus;
  currency: string;
  cost_code_standard: string | null;
  budget_tolerance_pct: Dec;
  vendor_name: string;
  discount_pct: Dec | null;
  lump_sum: Dec | null;
  awarded_at: string | null;
  projects: BundleProject[];
  lines: BundleLine[];
  split: Split;
  findings: Finding[];
  agreements: DocumentRef[];
}

export interface ShareInput {
  bundle_project_id: string;
  quantity: Dec | null;
  cost_line_id?: string | null;
}

export interface LineInput {
  code: string;
  description: string;
  unit: string;
  quantity: Dec;
  unit_rate: Dec | null;
  cost_code: string | null;
  shares?: ShareInput[];
}

export interface Terms {
  discount_pct: Dec | null;
  lump_sum: Dec | null;
}

export interface CallOffResult {
  document: DocumentRef;
  total: Dec;
  findings: Finding[];
}

export interface MyShareLine {
  code: string;
  description: string;
  unit: string;
  quantity: Dec | null;
  rate: Dec | null;
  net: Dec | null;
  called_off: Dec | null;
}

export interface MyShare {
  bundle_id: string;
  code: string;
  title: string;
  status: BundleStatus;
  kind: BundleKind;
  mode: BundleMode;
  currency: string;
  vendor_name: string;
  budget: Dec | null;
  gross: Dec;
  net: Dec;
  over_budget: boolean;
  lines: MyShareLine[];
  document: DocumentRef | null;
}

export interface Catalogue {
  standard: string | null;
  label: string | null;
  countries: string[];
  codes: { code: string; label: string }[];
}

export const cpbKeys = {
  all: ['central-purchasing'] as const,
  list: () => ['central-purchasing', 'list'] as const,
  detail: (id: string) => ['central-purchasing', 'detail', id] as const,
  preview: (id: string, terms: Terms) => ['central-purchasing', 'preview', id, terms] as const,
  myShares: (projectId: string) => ['central-purchasing', 'my-shares', projectId] as const,
  catalogues: (id?: string) => ['central-purchasing', 'catalogues', id ?? ''] as const,
};

export const cpbApi = {
  list: async () =>
    (await apiGet<{ items: BundleSummary[]; total: number }>(`/v1/central-purchasing/?limit=500`)).items,
  create: (body: { title: string; kind: BundleKind; mode: BundleMode; currency?: string }) =>
    apiPost<BundleDetail>(`/v1/central-purchasing/`, body),
  get: (id: string) => apiGet<BundleDetail>(`/v1/central-purchasing/${id}`),
  update: (id: string, body: Record<string, unknown>) => apiPatch<BundleDetail>(`/v1/central-purchasing/${id}`, body),
  remove: (id: string) => apiDelete<void>(`/v1/central-purchasing/${id}`),
  preview: (id: string, terms: Terms) => apiPost<BundleDetail>(`/v1/central-purchasing/${id}/preview`, terms),
  addProject: (id: string, projectId: string) =>
    apiPost<BundleDetail>(`/v1/central-purchasing/${id}/projects`, { project_id: projectId }),
  updateProject: (id: string, bpId: string, budget: Dec | null) =>
    apiPatch<BundleDetail>(
      `/v1/central-purchasing/${id}/projects/${bpId}`,
      budget == null ? { clear_budget: true } : { budget_amount: budget },
    ),
  removeProject: (id: string, bpId: string) => apiDelete<BundleDetail>(`/v1/central-purchasing/${id}/projects/${bpId}`),
  addLine: (id: string, body: LineInput) => apiPost<BundleDetail>(`/v1/central-purchasing/${id}/lines`, body),
  updateLine: (id: string, lineId: string, body: Partial<LineInput> & { clear_rate?: boolean }) =>
    apiPatch<BundleDetail>(`/v1/central-purchasing/${id}/lines/${lineId}`, body),
  removeLine: (id: string, lineId: string) => apiDelete<BundleDetail>(`/v1/central-purchasing/${id}/lines/${lineId}`),
  publish: (id: string) => apiPost<BundleDetail>(`/v1/central-purchasing/${id}/publish`, {}),
  award: (id: string, body: { vendor_name: string } & Terms) => apiPost<BundleDetail>(`/v1/central-purchasing/${id}/award`, body),
  callOff: (id: string, body: { project_id: string; lines: { line_id: string; quantity: Dec }[] }) =>
    apiPost<CallOffResult>(`/v1/central-purchasing/${id}/call-offs`, body),
  myShares: (projectId: string) =>
    apiGet<MyShare[]>(`/v1/central-purchasing/my-shares?project_id=${encodeURIComponent(projectId)}`),
  catalogues: (id?: string) =>
    apiGet<Catalogue[]>(`/v1/central-purchasing/catalogues${id ? `?bundle_id=${encodeURIComponent(id)}` : ''}`),
};
