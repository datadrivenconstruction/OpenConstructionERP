// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for File Approvals (W8).

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import {
  createStampTemplate,
  decideStep,
  getWorkflow,
  listStampTemplates,
  listWorkflows,
  submitForApproval,
  withdrawWorkflow,
} from './api';
import type {
  ApprovalDecidePayload,
  ApprovalWorkflow,
  ApprovalWorkflowCreatePayload,
  StampTemplate,
  StampTemplatePayload,
} from './types';

const KEY_LIST = 'file-approvals-list';
const KEY_DETAIL = 'file-approvals-detail';
const KEY_STAMPS = 'file-approvals-stamps';

export function useApprovals(
  projectId: string | null | undefined,
  statusFilter?: string,
): UseQueryResult<ApprovalWorkflow[], Error> {
  return useQuery({
    queryKey: [KEY_LIST, projectId, statusFilter ?? 'all'],
    queryFn: () => listWorkflows(projectId as string, statusFilter),
    enabled: Boolean(projectId),
    staleTime: 15_000,
  });
}

export function useApproval(
  workflowId: string | null | undefined,
): UseQueryResult<ApprovalWorkflow, Error> {
  return useQuery({
    queryKey: [KEY_DETAIL, workflowId],
    queryFn: () => getWorkflow(workflowId as string),
    enabled: Boolean(workflowId),
    staleTime: 5_000,
  });
}

export function useSubmitForApproval(): UseMutationResult<
  ApprovalWorkflow,
  Error,
  ApprovalWorkflowCreatePayload
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload) => submitForApproval(payload),
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: [KEY_LIST, created.project_id] });
    },
  });
}

export function useDecideApprovalStep(): UseMutationResult<
  ApprovalWorkflow,
  Error,
  { workflowId: string; stepId: string; payload: ApprovalDecidePayload }
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ workflowId, stepId, payload }) =>
      decideStep(workflowId, stepId, payload),
    onSuccess: (workflow) => {
      void qc.invalidateQueries({ queryKey: [KEY_DETAIL, workflow.id] });
      void qc.invalidateQueries({ queryKey: [KEY_LIST, workflow.project_id] });
    },
  });
}

export function useWithdrawApproval(): UseMutationResult<
  ApprovalWorkflow,
  Error,
  string
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (workflowId) => withdrawWorkflow(workflowId),
    onSuccess: (workflow) => {
      void qc.invalidateQueries({ queryKey: [KEY_DETAIL, workflow.id] });
      void qc.invalidateQueries({ queryKey: [KEY_LIST, workflow.project_id] });
    },
  });
}

export function useStampTemplates(
  projectId: string | null | undefined,
): UseQueryResult<StampTemplate[], Error> {
  return useQuery({
    queryKey: [KEY_STAMPS, projectId],
    queryFn: () => listStampTemplates(projectId),
    staleTime: 60_000,
  });
}

export function useCreateStampTemplate(): UseMutationResult<
  StampTemplate,
  Error,
  StampTemplatePayload
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload) => createStampTemplate(payload),
    onSuccess: (created) => {
      void qc.invalidateQueries({
        queryKey: [KEY_STAMPS, created.project_id ?? null],
      });
      void qc.invalidateQueries({ queryKey: [KEY_STAMPS] });
    },
  });
}

export const approvalQueryKeys = {
  list: KEY_LIST,
  detail: KEY_DETAIL,
  stamps: KEY_STAMPS,
};
