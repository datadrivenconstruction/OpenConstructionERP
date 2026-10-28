// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Commissioning (Cx) module.
 *
 * All endpoints are prefixed with /v1/commissioning/. Collection and action
 * routes carry a trailing slash to match the FastAPI routes exactly (the app
 * runs with redirect_slashes disabled); the single-system detail routes
 * (GET/PATCH/DELETE /systems/{id}) intentionally have no trailing slash.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type CxSystemStatus =
  | 'not_started'
  | 'in_progress'
  | 'tests_complete'
  | 'commissioned';

export type CxSystemType =
  | 'hvac'
  | 'electrical'
  | 'fire'
  | 'plumbing'
  | 'mechanical'
  | 'controls'
  | 'elevator'
  | 'security'
  | 'other';

export type ChecklistKind = 'prefunctional' | 'functional';
export type ItemStatus = 'pending' | 'pass' | 'fail' | 'na';
export type ItemResult = 'pass' | 'fail' | 'na';
export type IssueSeverity = 'low' | 'medium' | 'high' | 'critical';
export type IssueStatus = 'open' | 'closed';
export type ReadinessLevel = 'green' | 'amber' | 'red';

export interface ReadinessSummary {
  functional_total: number;
  functional_passed: number;
  functional_failed: number;
  functional_pending: number;
  functional_na: number;
  applicable: number;
  open_functional_items: number;
  open_critical_issues: number;
  readiness_pct: number;
  defined: boolean;
  can_commission: boolean;
  readiness_level: ReadinessLevel;
  blocking_reasons: string[];
  formula: string;
}

export interface CxSystem {
  id: string;
  project_id: string;
  name: string;
  system_type: CxSystemType | string;
  tag: string | null;
  location: string | null;
  description: string | null;
  status: CxSystemStatus;
  commissioned_at: string | null;
  commissioned_by: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  readiness: ReadinessSummary | null;
  created_at: string;
  updated_at: string;
}

export interface CxChecklist {
  id: string;
  system_id: string;
  kind: ChecklistKind;
  title: string;
  description: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CxChecklistItem {
  id: string;
  checklist_id: string;
  sequence: number;
  description: string;
  status: ItemStatus;
  result_note: string | null;
  verified_by: string | null;
  verified_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CxIssue {
  id: string;
  system_id: string;
  description: string;
  severity: IssueSeverity;
  status: IssueStatus;
  resolution: string | null;
  raised_by: string | null;
  closed_by: string | null;
  closed_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CxStats {
  total_systems: number;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  commissioned: number;
  open_issues: number;
  open_critical_issues: number;
  average_readiness_pct: number;
}

/* ── Payloads ──────────────────────────────────────────────────────────── */

export interface CreateSystemPayload {
  project_id: string;
  name: string;
  system_type?: CxSystemType;
  tag?: string;
  location?: string;
  description?: string;
  status?: CxSystemStatus;
}

export interface UpdateSystemPayload {
  name?: string;
  system_type?: CxSystemType;
  tag?: string;
  location?: string;
  description?: string;
  status?: Exclude<CxSystemStatus, 'commissioned'>;
}

export interface CreateChecklistPayload {
  kind: ChecklistKind;
  title: string;
  description?: string;
}

export interface CreateItemPayload {
  description: string;
  sequence?: number;
  status?: ItemStatus;
}

export interface ItemResultPayload {
  status: ItemResult;
  result_note?: string;
}

export interface CreateIssuePayload {
  description: string;
  severity?: IssueSeverity;
}

export interface UpdateIssuePayload {
  severity?: IssueSeverity;
  status?: IssueStatus;
  resolution?: string;
}

export interface CommissionPayload {
  note?: string;
}

/* ── System endpoints ──────────────────────────────────────────────────── */

export interface SystemFilters {
  project_id: string;
  status?: CxSystemStatus | '';
  type?: CxSystemType | '';
}

export async function fetchSystems(filters: SystemFilters): Promise<CxSystem[]> {
  const params = new URLSearchParams();
  params.set('project_id', filters.project_id);
  if (filters.status) params.set('status', filters.status);
  if (filters.type) params.set('type', filters.type);
  return apiGet<CxSystem[]>(`/v1/commissioning/systems/?${params.toString()}`);
}

export async function createSystem(data: CreateSystemPayload): Promise<CxSystem> {
  return apiPost<CxSystem>('/v1/commissioning/systems/', data);
}

export async function updateSystem(id: string, data: UpdateSystemPayload): Promise<CxSystem> {
  return apiPatch<CxSystem>(`/v1/commissioning/systems/${id}`, data);
}

export async function deleteSystem(id: string): Promise<void> {
  return apiDelete<void>(`/v1/commissioning/systems/${id}`);
}

export async function fetchReadiness(id: string): Promise<ReadinessSummary> {
  return apiGet<ReadinessSummary>(`/v1/commissioning/systems/${id}/readiness/`);
}

export async function commissionSystem(
  id: string,
  data: CommissionPayload = {},
): Promise<CxSystem> {
  return apiPost<CxSystem>(`/v1/commissioning/systems/${id}/commission/`, data);
}

export async function fetchCxStats(projectId: string): Promise<CxStats> {
  return apiGet<CxStats>(
    `/v1/commissioning/stats/?project_id=${encodeURIComponent(projectId)}`,
  );
}

/* ── Checklist endpoints ───────────────────────────────────────────────── */

export async function fetchChecklists(systemId: string): Promise<CxChecklist[]> {
  return apiGet<CxChecklist[]>(`/v1/commissioning/systems/${systemId}/checklists/`);
}

export async function createChecklist(
  systemId: string,
  data: CreateChecklistPayload,
): Promise<CxChecklist> {
  return apiPost<CxChecklist>(`/v1/commissioning/systems/${systemId}/checklists/`, data);
}

export async function deleteChecklist(checklistId: string): Promise<void> {
  return apiDelete<void>(`/v1/commissioning/checklists/${checklistId}`);
}

/* ── Item endpoints ────────────────────────────────────────────────────── */

export async function fetchItems(checklistId: string): Promise<CxChecklistItem[]> {
  return apiGet<CxChecklistItem[]>(`/v1/commissioning/checklists/${checklistId}/items/`);
}

export async function createItem(
  checklistId: string,
  data: CreateItemPayload,
): Promise<CxChecklistItem> {
  return apiPost<CxChecklistItem>(`/v1/commissioning/checklists/${checklistId}/items/`, data);
}

export async function setItemResult(
  itemId: string,
  data: ItemResultPayload,
): Promise<CxChecklistItem> {
  return apiPost<CxChecklistItem>(`/v1/commissioning/items/${itemId}/result/`, data);
}

export async function deleteItem(itemId: string): Promise<void> {
  return apiDelete<void>(`/v1/commissioning/items/${itemId}`);
}

/* ── Issue endpoints ───────────────────────────────────────────────────── */

export async function fetchIssues(systemId: string): Promise<CxIssue[]> {
  return apiGet<CxIssue[]>(`/v1/commissioning/systems/${systemId}/issues/`);
}

export async function createIssue(
  systemId: string,
  data: CreateIssuePayload,
): Promise<CxIssue> {
  return apiPost<CxIssue>(`/v1/commissioning/systems/${systemId}/issues/`, data);
}

export async function updateIssue(
  issueId: string,
  data: UpdateIssuePayload,
): Promise<CxIssue> {
  return apiPatch<CxIssue>(`/v1/commissioning/issues/${issueId}`, data);
}

export async function deleteIssue(issueId: string): Promise<void> {
  return apiDelete<void>(`/v1/commissioning/issues/${issueId}`);
}
