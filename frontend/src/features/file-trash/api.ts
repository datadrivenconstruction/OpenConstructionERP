// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** API client for the File Trash feature (W2).
 *
 * Endpoints live at `/api/v1/file-trash/`. Auto-mounted by the
 * module loader from `app/modules/file_trash/router.py`.
 */

import { apiGet, apiPost, ApiError } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import type {
  TrashItem,
  TrashListResponse,
  TrashSoftDeletePayload,
  TrashStats,
} from './types';

const BASE = '/v1/file-trash';

export async function listTrash(
  projectId: string,
  options: { offset?: number; limit?: number } = {},
): Promise<TrashListResponse> {
  const params = new URLSearchParams({ project_id: projectId });
  if (options.offset !== undefined) params.set('offset', String(options.offset));
  if (options.limit !== undefined) params.set('limit', String(options.limit));
  return apiGet<TrashListResponse>(`${BASE}/?${params.toString()}`);
}

export async function trashStats(projectId: string): Promise<TrashStats> {
  const params = new URLSearchParams({ project_id: projectId });
  return apiGet<TrashStats>(`${BASE}/stats/?${params.toString()}`);
}

export async function softDelete(
  payload: TrashSoftDeletePayload,
): Promise<TrashItem> {
  return apiPost<TrashItem, TrashSoftDeletePayload>(`${BASE}/`, payload);
}

export async function restoreFromTrash(trashId: string): Promise<TrashItem> {
  return apiPost<TrashItem, Record<string, never>>(
    `${BASE}/${trashId}/restore/`,
    {},
  );
}

/** DELETE with a JSON body — the shared apiDelete helper drops the
 * body, so we fall back to a raw fetch. The endpoint requires the
 * matching restore token, so this is a "real" body, not a hint. */
export async function purgeFromTrash(
  trashId: string,
  confirmToken: string,
): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`/api${BASE}/${trashId}`, {
    method: 'DELETE',
    headers,
    body: JSON.stringify({ confirm_token: confirmToken }),
  });
  if (!res.ok) {
    let body: unknown = res.statusText;
    try {
      const text = await res.text();
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    } catch {
      // keep statusText
    }
    throw new ApiError(res.status, res.statusText, body);
  }
}

export const fileTrashKeys = {
  list: 'file-trash-list' as const,
  stats: 'file-trash-stats' as const,
};
