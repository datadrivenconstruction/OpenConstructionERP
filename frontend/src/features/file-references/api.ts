// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** API client for the File References feature (W9).
 *
 * Endpoints live at `/api/v1/file-references/`. Auto-mounted by the
 * module loader from `app/modules/file_references/router.py`.
 */

import { apiDelete, apiGet, apiPost } from '@/shared/lib/api';
import type {
  FileKind,
  FileReferenceCreatePayload,
  FileReferenceListResponse,
  FileReferenceResponse,
  Iso19650Result,
  NamingViolationListResponse,
  NamingViolationResponse,
  ProjectScanResponse,
  TargetType,
} from './types';

const BASE = '/v1/file-references';

// ── ISO 19650 ──────────────────────────────────────────────────────────

export async function validateName(
  filename: string,
  ruleSet: 'iso19650' | 'none' = 'iso19650',
): Promise<Iso19650Result> {
  return apiPost<Iso19650Result, { filename: string; rule_set: string }>(
    `${BASE}/validate-name/`,
    { filename, rule_set: ruleSet },
  );
}

export async function scanProject(
  projectId: string,
  ruleSet: 'iso19650' | 'none' = 'iso19650',
): Promise<ProjectScanResponse> {
  const params = new URLSearchParams({ project_id: projectId, rule_set: ruleSet });
  return apiPost<ProjectScanResponse, Record<string, never>>(
    `${BASE}/scan-project/?${params.toString()}`,
    {},
  );
}

export interface ListViolationsArgs {
  projectId: string;
  includeAcknowledged?: boolean;
  limit?: number;
  offset?: number;
}

export async function listViolations(
  args: ListViolationsArgs,
): Promise<NamingViolationListResponse> {
  const params = new URLSearchParams({
    project_id: args.projectId,
    include_acknowledged: String(Boolean(args.includeAcknowledged)),
  });
  if (args.limit !== undefined) params.set('limit', String(args.limit));
  if (args.offset !== undefined) params.set('offset', String(args.offset));
  return apiGet<NamingViolationListResponse>(
    `${BASE}/violations/?${params.toString()}`,
  );
}

export async function acknowledgeViolation(
  violationId: string,
): Promise<NamingViolationResponse> {
  return apiPost<NamingViolationResponse, Record<string, never>>(
    `${BASE}/violations/${violationId}/acknowledge/`,
    {},
  );
}

// ── Cross-entity references ──────────────────────────────────────────

export interface ListReferencesForFileArgs {
  projectId: string;
  kind: FileKind;
  fileId: string;
}

export async function listReferencesForFile(
  args: ListReferencesForFileArgs,
): Promise<FileReferenceListResponse> {
  const params = new URLSearchParams({
    project_id: args.projectId,
    kind: args.kind,
    file_id: args.fileId,
  });
  return apiGet<FileReferenceListResponse>(`${BASE}/?${params.toString()}`);
}

export interface ListFilesForTargetArgs {
  projectId: string;
  targetType: TargetType;
  targetId: string;
}

export async function listFilesForTarget(
  args: ListFilesForTargetArgs,
): Promise<FileReferenceListResponse> {
  const params = new URLSearchParams({
    project_id: args.projectId,
    target_type: args.targetType,
    target_id: args.targetId,
  });
  return apiGet<FileReferenceListResponse>(
    `${BASE}/by-target/?${params.toString()}`,
  );
}

export async function createReference(
  payload: FileReferenceCreatePayload,
): Promise<FileReferenceResponse> {
  return apiPost<FileReferenceResponse, FileReferenceCreatePayload>(
    `${BASE}/`,
    payload,
  );
}

export async function deleteReference(
  referenceId: string,
  projectId: string,
): Promise<void> {
  const params = new URLSearchParams({ project_id: projectId });
  await apiDelete<void>(`${BASE}/${referenceId}/?${params.toString()}`);
}

export const fileReferenceKeys = {
  violations: 'file-references-violations' as const,
  forFile: 'file-references-for-file' as const,
  forTarget: 'file-references-for-target' as const,
  validate: 'file-references-validate' as const,
};
