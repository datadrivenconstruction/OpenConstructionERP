// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

// ---------------------------------------------------------------------------
// Workflow types
// ---------------------------------------------------------------------------

/**
 * The per-step action types the approval engine dispatches
 * (``ALLOWED_ACTION_TYPES`` in backend/app/modules/enterprise_workflows/service.py).
 */
export const WORKFLOW_ACTION_TYPES = ['approve', 'review', 'sign_off', 'notify'] as const;
export type WorkflowActionType = (typeof WORKFLOW_ACTION_TYPES)[number];

/**
 * The action types the step editor offers. ``approve_request`` does not read
 * ``action_type`` yet, so every step blocks until someone decides it; offering
 * "review" or "notify" would promise a step that lets the request through on
 * its own. Stored steps of those types still display by their name.
 */
export const OFFERED_ACTION_TYPES: readonly WorkflowActionType[] = ['approve', 'sign_off'];

/**
 * Roles a step can require. The engine lets a user decide a step when their
 * role ranks at or above the step's ``role``; the field roles are left out
 * because they rank below viewer and carry no permissions yet.
 */
export const WORKFLOW_STEP_ROLES = ['viewer', 'editor', 'manager', 'admin'] as const;

/**
 * One approval step, stored by the backend as a plain dict. The engine reads
 * exactly these keys: ``role`` gates who may decide the step, ``assignee_id``
 * pins it to one user, and a step with neither is open to anyone.
 */
export interface WorkflowStep {
  role?: string | null;
  action_type?: WorkflowActionType;
  assignee_id?: string | null;
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

export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';

export interface ApprovalRequest {
  id: string;
  workflow_id: string;
  entity_type: string;
  entity_id: string;
  requested_by: string;
  status: ApprovalStatus;
  current_step: number;
  decision_notes: string | null;
  decided_by: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SubmitApprovalBody {
  workflow_id: string;
  entity_type: string;
  entity_id: string;
  metadata?: Record<string, unknown>;
}

export interface ApprovalActionBody {
  decision_notes?: string | null;
}

/** The paged envelope both list routes answer with. */
interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
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
  const page = await apiGet<Page<Workflow>>(`/v1/enterprise-workflows/${query ? '?' + query : ''}`);
  return page.items;
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
  entity_type?: string;
}): Promise<ApprovalRequest[]> {
  const qs = new URLSearchParams();
  if (params?.workflow_id) qs.set('workflow_id', params.workflow_id);
  if (params?.status) qs.set('status', params.status);
  if (params?.entity_type) qs.set('entity_type', params.entity_type);
  const query = qs.toString();
  // The router declares ``/requests/`` and the app does not redirect slashes:
  // without it the path falls through to ``/{workflow_id}`` and fails as a 422.
  const page = await apiGet<Page<ApprovalRequest>>(
    `/v1/enterprise-workflows/requests/${query ? '?' + query : ''}`,
  );
  return page.items;
}

/**
 * How many approval requests are pending, across every page.
 *
 * Counted from the envelope's ``total`` with a one-row page, so the figure is
 * right however many requests exist and whatever the list below is filtered to.
 */
export async function fetchPendingApprovalCount(): Promise<number> {
  const page = await apiGet<Page<ApprovalRequest>>('/v1/enterprise-workflows/requests/?status=pending&limit=1');
  return page.total;
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
