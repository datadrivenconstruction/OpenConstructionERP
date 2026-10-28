// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** React Query hooks for File References. */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import {
  acknowledgeViolation,
  createReference,
  deleteReference,
  fileReferenceKeys,
  listFilesForTarget,
  listReferencesForFile,
  listViolations,
  scanProject,
  validateName,
  type ListFilesForTargetArgs,
  type ListReferencesForFileArgs,
  type ListViolationsArgs,
} from './api';
import type {
  FileReferenceCreatePayload,
  FileReferenceListResponse,
  FileReferenceResponse,
  Iso19650Result,
  NamingViolationListResponse,
  NamingViolationResponse,
  ProjectScanResponse,
} from './types';

// ── ISO 19650 ──────────────────────────────────────────────────────────

export function useValidateName(): UseMutationResult<
  Iso19650Result,
  Error,
  { filename: string; ruleSet?: 'iso19650' | 'none' }
> {
  return useMutation<
    Iso19650Result,
    Error,
    { filename: string; ruleSet?: 'iso19650' | 'none' }
  >({
    mutationFn: ({ filename, ruleSet }) => validateName(filename, ruleSet),
  });
}

export function useScanProject(
  projectId: string | null,
): UseMutationResult<ProjectScanResponse, Error, { ruleSet?: 'iso19650' | 'none' }> {
  const qc = useQueryClient();
  return useMutation<
    ProjectScanResponse,
    Error,
    { ruleSet?: 'iso19650' | 'none' }
  >({
    mutationFn: ({ ruleSet }) =>
      scanProject(projectId as string, ruleSet ?? 'iso19650'),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: [fileReferenceKeys.violations, projectId],
      });
    },
  });
}

export function useViolations(
  args: ListViolationsArgs | null,
): ReturnType<typeof useQuery<NamingViolationListResponse>> {
  return useQuery<NamingViolationListResponse>({
    queryKey: [
      fileReferenceKeys.violations,
      args?.projectId,
      args?.includeAcknowledged,
      args?.limit,
      args?.offset,
    ],
    queryFn: () => listViolations(args as ListViolationsArgs),
    enabled: Boolean(args?.projectId),
    staleTime: 30_000,
  });
}

export function useAcknowledgeViolation(
  projectId: string | null,
): UseMutationResult<NamingViolationResponse, Error, string> {
  const qc = useQueryClient();
  return useMutation<NamingViolationResponse, Error, string>({
    mutationFn: (violationId) => acknowledgeViolation(violationId),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: [fileReferenceKeys.violations, projectId],
      });
    },
  });
}

// ── Cross-entity references ──────────────────────────────────────────

export function useReferencesForFile(
  args: ListReferencesForFileArgs | null,
): ReturnType<typeof useQuery<FileReferenceListResponse>> {
  return useQuery<FileReferenceListResponse>({
    queryKey: [
      fileReferenceKeys.forFile,
      args?.projectId,
      args?.kind,
      args?.fileId,
    ],
    queryFn: () => listReferencesForFile(args as ListReferencesForFileArgs),
    enabled: Boolean(args && args.projectId && args.fileId),
    staleTime: 30_000,
  });
}

export function useFilesForTarget(
  args: ListFilesForTargetArgs | null,
): ReturnType<typeof useQuery<FileReferenceListResponse>> {
  return useQuery<FileReferenceListResponse>({
    queryKey: [
      fileReferenceKeys.forTarget,
      args?.projectId,
      args?.targetType,
      args?.targetId,
    ],
    queryFn: () => listFilesForTarget(args as ListFilesForTargetArgs),
    enabled: Boolean(args && args.projectId && args.targetId),
    staleTime: 30_000,
  });
}

export function useCreateReference(
  args: ListReferencesForFileArgs | null,
): UseMutationResult<FileReferenceResponse, Error, FileReferenceCreatePayload> {
  const qc = useQueryClient();
  return useMutation<FileReferenceResponse, Error, FileReferenceCreatePayload>({
    mutationFn: (payload) => createReference(payload),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: [fileReferenceKeys.forFile, args?.projectId, args?.kind, args?.fileId],
      });
      qc.invalidateQueries({ queryKey: [fileReferenceKeys.forTarget] });
    },
  });
}

export function useDeleteReference(
  args: ListReferencesForFileArgs | null,
): UseMutationResult<void, Error, string> {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (referenceId) =>
      deleteReference(referenceId, args?.projectId ?? ''),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: [fileReferenceKeys.forFile, args?.projectId, args?.kind, args?.fileId],
      });
      qc.invalidateQueries({ queryKey: [fileReferenceKeys.forTarget] });
    },
  });
}
