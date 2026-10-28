// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** React Query hooks for the W4 file-tags feature. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  assignTag,
  createTag,
  deleteTag,
  fetchTags,
  fetchTagsForFile,
  seedDefaultTags,
  unassignTag,
  updateTag,
} from './api';
import type {
  BulkAssignPayload,
  BulkAssignResult,
  CreateTagPayload,
  FileKind,
  SeedDefaultsResult,
  TagRecord,
  UpdateTagPayload,
} from './types';

const KEY_TAGS = 'file-tags-list';
const KEY_TAGS_BY_FILE = 'file-tags-by-file';

export function useFileTags(
  projectId: string | null | undefined,
  category?: string,
) {
  return useQuery<TagRecord[]>({
    queryKey: [KEY_TAGS, projectId, category ?? null],
    queryFn: () => fetchTags(projectId as string, category),
    enabled: Boolean(projectId),
    staleTime: 30_000,
  });
}

export function useTagsByFile(
  projectId: string | null | undefined,
  kind: FileKind | null | undefined,
  fileId: string | null | undefined,
) {
  return useQuery<TagRecord[]>({
    queryKey: [KEY_TAGS_BY_FILE, projectId, kind, fileId],
    queryFn: () =>
      fetchTagsForFile(projectId as string, kind as FileKind, fileId as string),
    enabled: Boolean(projectId && kind && fileId),
    staleTime: 30_000,
  });
}

export function useCreateTag() {
  const qc = useQueryClient();
  return useMutation<TagRecord, Error, CreateTagPayload>({
    mutationFn: (payload) => createTag(payload),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: [KEY_TAGS, vars.project_id] });
    },
  });
}

export function useUpdateTag() {
  const qc = useQueryClient();
  return useMutation<
    TagRecord,
    Error,
    { tagId: string; projectId: string; payload: UpdateTagPayload }
  >({
    mutationFn: ({ tagId, projectId, payload }) =>
      updateTag(tagId, projectId, payload),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: [KEY_TAGS, vars.projectId] });
      qc.invalidateQueries({ queryKey: [KEY_TAGS_BY_FILE, vars.projectId] });
    },
  });
}

export function useDeleteTag() {
  const qc = useQueryClient();
  return useMutation<void, Error, { tagId: string; projectId: string }>({
    mutationFn: ({ tagId, projectId }) => deleteTag(tagId, projectId),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: [KEY_TAGS, vars.projectId] });
      qc.invalidateQueries({ queryKey: [KEY_TAGS_BY_FILE, vars.projectId] });
    },
  });
}

export function useAssignTag() {
  const qc = useQueryClient();
  return useMutation<
    BulkAssignResult,
    Error,
    { tagId: string; projectId: string; payload: BulkAssignPayload }
  >({
    mutationFn: ({ tagId, projectId, payload }) =>
      assignTag(tagId, projectId, payload),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: [KEY_TAGS, vars.projectId] });
      qc.invalidateQueries({ queryKey: [KEY_TAGS_BY_FILE, vars.projectId] });
    },
  });
}

export function useUnassignTag() {
  const qc = useQueryClient();
  return useMutation<
    BulkAssignResult,
    Error,
    { tagId: string; projectId: string; payload: BulkAssignPayload }
  >({
    mutationFn: ({ tagId, projectId, payload }) =>
      unassignTag(tagId, projectId, payload),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: [KEY_TAGS, vars.projectId] });
      qc.invalidateQueries({ queryKey: [KEY_TAGS_BY_FILE, vars.projectId] });
    },
  });
}

export function useSeedDefaultTags() {
  const qc = useQueryClient();
  return useMutation<SeedDefaultsResult, Error, string>({
    mutationFn: (projectId) => seedDefaultTags(projectId),
    onSuccess: (_, projectId) => {
      qc.invalidateQueries({ queryKey: [KEY_TAGS, projectId] });
    },
  });
}

export const fileTagsKeys = {
  list: KEY_TAGS,
  byFile: KEY_TAGS_BY_FILE,
};
