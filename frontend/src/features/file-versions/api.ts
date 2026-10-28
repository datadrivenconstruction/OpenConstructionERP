// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** API client for the File Versioning feature (W1).
 *
 * Endpoints live at `/api/v1/file-versions/`. Auto-mounted by the
 * module loader from `app/modules/file_versions/router.py`.
 */

import { apiGet, apiPost } from '@/shared/lib/api';
import type {
  FileKind,
  FileVersionCreatePayload,
  FileVersionResponse,
} from './types';

const BASE = '/v1/file-versions';

/** List the version chain for a file, newest first. */
export async function listVersions(
  fileId: string,
  kind: FileKind,
): Promise<FileVersionResponse[]> {
  const params = new URLSearchParams({ file_id: fileId, kind });
  return apiGet<FileVersionResponse[]>(`${BASE}/?${params.toString()}`);
}

/** Fetch a single version row by id. */
export async function getVersion(versionId: string): Promise<FileVersionResponse> {
  return apiGet<FileVersionResponse>(`${BASE}/${versionId}/`);
}

/** Register a new version row (caller already uploaded the file). */
export async function createVersion(
  payload: FileVersionCreatePayload,
): Promise<FileVersionResponse> {
  return apiPost<FileVersionResponse, FileVersionCreatePayload>(`${BASE}/`, payload);
}

/** Promote a historical version back to current. */
export async function restoreVersion(versionId: string): Promise<FileVersionResponse> {
  return apiPost<FileVersionResponse, Record<string, never>>(
    `${BASE}/${versionId}/restore/`,
    {},
  );
}

export const fileVersionKeys = {
  list: 'file-versions-list' as const,
  detail: 'file-versions-detail' as const,
};
