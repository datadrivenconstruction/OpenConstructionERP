// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** API client for the W3 file-search module. */

import { apiDelete, apiGet, apiPost } from '@/shared/lib/api';
import type {
  IndexFileRequest,
  IndexFileResponse,
  ReindexResponse,
  SearchMode,
  SearchResponse,
  FileKind,
} from './types';

const BASE = '/v1/file-search';

/** Run a content or filename search.
 *
 * The backend tolerates `q=""` by returning `{ total: 0, hits: [] }`,
 * so callers can pass through the raw debounced input without a
 * special-case guard.
 */
export async function searchContent(
  projectId: string,
  q: string,
  mode: SearchMode = 'content',
  kind?: FileKind,
  limit = 50,
): Promise<SearchResponse> {
  const params = new URLSearchParams({
    project_id: projectId,
    q,
    mode,
    limit: String(limit),
  });
  if (kind) params.set('kind', kind);
  return apiGet<SearchResponse>(`${BASE}/?${params.toString()}`);
}

/** Trigger indexing for a single file. Called after a successful upload. */
export async function indexFile(payload: IndexFileRequest): Promise<IndexFileResponse> {
  return apiPost<IndexFileResponse, IndexFileRequest>(`${BASE}/index/`, payload);
}

/** Re-OCR every file in a project. */
export async function reindexProject(projectId: string): Promise<ReindexResponse> {
  return apiPost<ReindexResponse, undefined>(
    `${BASE}/reindex/?project_id=${encodeURIComponent(projectId)}`,
  );
}

/** Remove a single file from the index. */
export async function removeFromIndex(
  projectId: string,
  fileId: string,
  kind?: FileKind,
): Promise<void> {
  const params = new URLSearchParams({ project_id: projectId });
  if (kind) params.set('kind', kind);
  return apiDelete<void>(
    `${BASE}/${encodeURIComponent(fileId)}/?${params.toString()}`,
  );
}
