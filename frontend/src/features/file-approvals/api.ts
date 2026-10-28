// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// API client for File Approvals (W8).
//
// Endpoints (mounted at /api/v1/file-approvals):
//   GET    /v1/file-approvals/?project_id={uuid}&status={s}
//   POST   /v1/file-approvals/
//   GET    /v1/file-approvals/{id}/
//   POST   /v1/file-approvals/{id}/steps/{stepId}/decide/
//   POST   /v1/file-approvals/{id}/withdraw/
//   GET    /v1/file-approvals/{id}/stamped/
//   GET    /v1/file-approvals/stamp-templates/?project_id={uuid}
//   POST   /v1/file-approvals/stamp-templates/

import {
  apiGet,
  apiPost,
  extractErrorMessageFromBody,
  triggerDownload,
} from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import type {
  ApprovalDecidePayload,
  ApprovalWorkflow,
  ApprovalWorkflowCreatePayload,
  StampTemplate,
  StampTemplatePayload,
} from './types';

const BASE = '/v1/file-approvals';

/**
 * Download the project's approvals register as an Excel workbook.
 *
 * Mirrors the RFI-log export trigger: an authenticated binary GET against
 * ``/v1/file-approvals/export/`` (note the trailing slash - the app runs
 * with ``redirect_slashes=False``, so the no-slash form would 404), then a
 * client-side file save. Throws a useful message on a non-2xx so the caller
 * can surface it in a toast.
 */
export async function downloadApprovalRegister(projectId: string): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const response = await fetch(
    `/api${BASE}/export/?project_id=${encodeURIComponent(projectId)}`,
    { method: 'GET', headers },
  );
  if (!response.ok) {
    let detail = `Export failed (HTTP ${response.status})`;
    try {
      detail = extractErrorMessageFromBody(await response.json()) ?? detail;
    } catch {
      // Non-JSON error body - keep the generic message.
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename =
    disposition?.match(/filename="?(.+)"?/)?.[1] || 'approval_register.xlsx';
  triggerDownload(blob, filename);
}

export async function listWorkflows(
  projectId: string,
  statusFilter?: string,
): Promise<ApprovalWorkflow[]> {
  const params = new URLSearchParams({ project_id: projectId });
  if (statusFilter) params.set('status', statusFilter);
  return apiGet<ApprovalWorkflow[]>(`${BASE}/?${params.toString()}`);
}

export async function getWorkflow(workflowId: string): Promise<ApprovalWorkflow> {
  return apiGet<ApprovalWorkflow>(`${BASE}/${workflowId}/`);
}

export async function submitForApproval(
  payload: ApprovalWorkflowCreatePayload,
): Promise<ApprovalWorkflow> {
  return apiPost<ApprovalWorkflow, ApprovalWorkflowCreatePayload>(
    `${BASE}/`,
    payload,
  );
}

export async function decideStep(
  workflowId: string,
  stepId: string,
  payload: ApprovalDecidePayload,
): Promise<ApprovalWorkflow> {
  return apiPost<ApprovalWorkflow, ApprovalDecidePayload>(
    `${BASE}/${workflowId}/steps/${stepId}/decide/`,
    payload,
  );
}

export async function withdrawWorkflow(
  workflowId: string,
): Promise<ApprovalWorkflow> {
  return apiPost<ApprovalWorkflow>(`${BASE}/${workflowId}/withdraw/`, {});
}

export async function listStampTemplates(
  projectId?: string | null,
): Promise<StampTemplate[]> {
  const params = new URLSearchParams();
  if (projectId) params.set('project_id', projectId);
  const qs = params.toString();
  return apiGet<StampTemplate[]>(`${BASE}/stamp-templates/${qs ? `?${qs}` : ''}`);
}

export async function createStampTemplate(
  payload: StampTemplatePayload,
): Promise<StampTemplate> {
  return apiPost<StampTemplate, StampTemplatePayload>(
    `${BASE}/stamp-templates/`,
    payload,
  );
}
