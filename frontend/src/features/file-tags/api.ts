// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** API client for the W4 file-tags module. */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import type {
  BulkAssignPayload,
  BulkAssignResult,
  CreateTagPayload,
  FileKind,
  SeedDefaultsResult,
  TagRecord,
  UpdateTagPayload,
} from './types';

const BASE = '/v1/file-tags';

export async function fetchTags(
  projectId: string,
  category?: string,
): Promise<TagRecord[]> {
  const params = new URLSearchParams({ project_id: projectId });
  if (category) params.set('category', category);
  return apiGet<TagRecord[]>(`${BASE}/?${params.toString()}`);
}

export async function createTag(payload: CreateTagPayload): Promise<TagRecord> {
  return apiPost<TagRecord, CreateTagPayload>(`${BASE}/`, payload);
}

export async function updateTag(
  tagId: string,
  projectId: string,
  payload: UpdateTagPayload,
): Promise<TagRecord> {
  const params = new URLSearchParams({ project_id: projectId });
  return apiPatch<TagRecord, UpdateTagPayload>(
    `${BASE}/${encodeURIComponent(tagId)}/?${params.toString()}`,
    payload,
  );
}

export async function deleteTag(tagId: string, projectId: string): Promise<void> {
  const params = new URLSearchParams({ project_id: projectId });
  return apiDelete<void>(
    `${BASE}/${encodeURIComponent(tagId)}/?${params.toString()}`,
  );
}

export async function assignTag(
  tagId: string,
  projectId: string,
  payload: BulkAssignPayload,
): Promise<BulkAssignResult> {
  const params = new URLSearchParams({ project_id: projectId });
  return apiPost<BulkAssignResult, BulkAssignPayload>(
    `${BASE}/${encodeURIComponent(tagId)}/assign/?${params.toString()}`,
    payload,
  );
}

export async function unassignTag(
  tagId: string,
  projectId: string,
  payload: BulkAssignPayload,
): Promise<BulkAssignResult> {
  const params = new URLSearchParams({ project_id: projectId });
  return apiPost<BulkAssignResult, BulkAssignPayload>(
    `${BASE}/${encodeURIComponent(tagId)}/unassign/?${params.toString()}`,
    payload,
  );
}

export async function fetchTagsForFile(
  projectId: string,
  kind: FileKind,
  fileId: string,
): Promise<TagRecord[]> {
  const params = new URLSearchParams({
    project_id: projectId,
    kind,
    file_id: fileId,
  });
  return apiGet<TagRecord[]>(`${BASE}/by-file/?${params.toString()}`);
}

export async function seedDefaultTags(projectId: string): Promise<SeedDefaultsResult> {
  const params = new URLSearchParams({ project_id: projectId });
  return apiPost<SeedDefaultsResult, undefined>(
    `${BASE}/seed-defaults/?${params.toString()}`,
  );
}
