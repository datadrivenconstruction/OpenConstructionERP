// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { normalizeListResponse } from '@/shared/lib/apiHelpers';

// ---------------------------------------------------------------------------
// Workflow types
// ---------------------------------------------------------------------------

export interface WorkflowStep {
  step_order: number;
  approver_role: string;
  approver_id: string | null;
  action: string;
}

export interface Workflow {
  id: string;
  project_id: string | null;
  name: string;
  description: string | null;
  entity_type: string;
  steps: WorkflowStep[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateWorkflowBody {
  project_id?: string | null;
  name: string;
  description?: string | null;
  entity_type: string;
  steps: WorkflowStep[];
  is_active?: boolean;
}

export interface UpdateWorkflowBody {
  name?: string;
  description?: string | null;
  entity_type?: string;
  steps?: WorkflowStep[];
  is_active?: boolean;
}

// ---------------------------------------------------------------------------
// Approval request types
// ---------------------------------------------------------------------------

export type ApprovalStatus = 'pending' | 'approved' | 'rejected';

export interface ApprovalRequest {
  id: string;
  workflow_id: string;
  entity_type: string;
  entity_id: string;
  requester_id: string;
  status: ApprovalStatus;
  current_step: number;
  comments: string | null;
  decided_by: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SubmitApprovalBody {
  workflow_id: string;
  entity_type: string;
  entity_id: string;
  comments?: string | null;
}

export interface ApprovalActionBody {
  comments?: string | null;
}

// ---------------------------------------------------------------------------
// Workflow API calls
// ---------------------------------------------------------------------------

export async function fetchWorkflows(params?: {
  project_id?: string;
  entity_type?: string;
  is_active?: boolean;
}): Promise<Workflow[]> {
  const qs = new URLSearchParams();
  if (params?.project_id) qs.set('project_id', params.project_id);
  if (params?.entity_type) qs.set('entity_type', params.entity_type);
  if (params?.is_active !== undefined) qs.set('is_active', String(params.is_active));
  const query = qs.toString();
  // The server answers with a page envelope, {items, total, offset, limit}.
  const page = await apiGet<Workflow[] | { items: Workflow[] }>(
    `/v1/enterprise-workflows/${query ? '?' + query : ''}`,
  );
  return normalizeListResponse(page);
}

export async function fetchWorkflow(id: string): Promise<Workflow> {
  return apiGet<Workflow>(`/v1/enterprise-workflows/${id}`);
}

export async function createWorkflow(body: CreateWorkflowBody): Promise<Workflow> {
  return apiPost<Workflow, CreateWorkflowBody>('/v1/enterprise-workflows/', body);
}

export async function updateWorkflow(id: string, body: UpdateWorkflowBody): Promise<Workflow> {
  return apiPatch<Workflow, UpdateWorkflowBody>(`/v1/enterprise-workflows/${id}`, body);
}

export async function deleteWorkflow(id: string): Promise<void> {
  return apiDelete(`/v1/enterprise-workflows/${id}`);
}

// ---------------------------------------------------------------------------
// Approval request API calls
// ---------------------------------------------------------------------------

export async function fetchApprovalRequests(params?: {
  workflow_id?: string;
  status?: ApprovalStatus;
  requester_id?: string;
}): Promise<ApprovalRequest[]> {
  const qs = new URLSearchParams();
  if (params?.workflow_id) qs.set('workflow_id', params.workflow_id);
  if (params?.status) qs.set('status', params.status);
  if (params?.requester_id) qs.set('requester_id', params.requester_id);
  const query = qs.toString();
  // The route is /requests/ with the slash (the app does not redirect slashes),
  // and it answers with a page envelope rather than a bare array.
  const page = await apiGet<ApprovalRequest[] | { items: ApprovalRequest[] }>(
    `/v1/enterprise-workflows/requests/${query ? '?' + query : ''}`,
  );
  return normalizeListResponse(page);
}

export async function fetchApprovalRequest(id: string): Promise<ApprovalRequest> {
  return apiGet<ApprovalRequest>(`/v1/enterprise-workflows/requests/${id}`);
}

export async function submitApprovalRequest(body: SubmitApprovalBody): Promise<ApprovalRequest> {
  return apiPost<ApprovalRequest, SubmitApprovalBody>('/v1/enterprise-workflows/requests/', body);
}

export async function approveRequest(id: string, body?: ApprovalActionBody): Promise<ApprovalRequest> {
  return apiPost<ApprovalRequest, ApprovalActionBody | undefined>(
    `/v1/enterprise-workflows/requests/${id}/approve/`,
    body,
  );
}

export async function rejectRequest(id: string, body?: ApprovalActionBody): Promise<ApprovalRequest> {
  return apiPost<ApprovalRequest, ApprovalActionBody | undefined>(
    `/v1/enterprise-workflows/requests/${id}/reject/`,
    body,
  );
}
