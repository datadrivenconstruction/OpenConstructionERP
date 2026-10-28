// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** React Query hooks for File Trash. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  fileTrashKeys,
  listTrash,
  purgeFromTrash,
  restoreFromTrash,
  softDelete,
  trashStats,
} from './api';
import type {
  TrashItem,
  TrashListResponse,
  TrashSoftDeletePayload,
  TrashStats,
} from './types';

export function useFileTrash(
  projectId: string | null | undefined,
  options: { offset?: number; limit?: number } = {},
) {
  return useQuery<TrashListResponse>({
    queryKey: [fileTrashKeys.list, projectId, options.offset ?? 0, options.limit ?? 50],
    queryFn: () =>
      listTrash(projectId as string, {
        offset: options.offset,
        limit: options.limit,
      }),
    enabled: Boolean(projectId),
    staleTime: 15_000,
  });
}

export function useFileTrashStats(projectId: string | null | undefined) {
  return useQuery<TrashStats>({
    queryKey: [fileTrashKeys.stats, projectId],
    queryFn: () => trashStats(projectId as string),
    enabled: Boolean(projectId),
    staleTime: 30_000,
  });
}

interface InvalidateOptions {
  /** When true, also invalidate the file-manager list/tree so the UI
   * reflects the deletion or restore immediately. */
  invalidateFileManager?: boolean;
}

function invalidateAll(
  qc: ReturnType<typeof useQueryClient>,
  projectId: string | null | undefined,
  opts: InvalidateOptions = {},
) {
  qc.invalidateQueries({ queryKey: [fileTrashKeys.list, projectId] });
  qc.invalidateQueries({ queryKey: [fileTrashKeys.stats, projectId] });
  if (opts.invalidateFileManager) {
    qc.invalidateQueries({ queryKey: ['file-manager-list', projectId] });
    qc.invalidateQueries({ queryKey: ['file-manager-tree', projectId] });
  }
}

export function useSoftDelete(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation<TrashItem, Error, TrashSoftDeletePayload>({
    mutationFn: (payload) => softDelete(payload),
    onSuccess: () => invalidateAll(qc, projectId, { invalidateFileManager: true }),
  });
}

export function useRestoreFromTrash(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation<TrashItem, Error, string>({
    mutationFn: (trashId) => restoreFromTrash(trashId),
    onSuccess: () => invalidateAll(qc, projectId, { invalidateFileManager: true }),
  });
}

interface PurgeArgs {
  trashId: string;
  confirmToken: string;
}

export function usePurgeTrash(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation<void, Error, PurgeArgs>({
    mutationFn: ({ trashId, confirmToken }) => purgeFromTrash(trashId, confirmToken),
    onSuccess: () => invalidateAll(qc, projectId),
  });
}
