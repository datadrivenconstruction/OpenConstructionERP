// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for the file-saved-views (W5) module.

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import type {
  SavedViewCreatePayload,
  SavedViewListResponse,
  SavedViewResponse,
  SavedViewUpdatePayload,
} from './types';

const BASE = '/v1/file-saved-views';

export async function fetchSavedViews(
  projectId: string | null | undefined,
): Promise<SavedViewListResponse> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return apiGet<SavedViewListResponse>(`${BASE}/${qs}`);
}

export async function createSavedView(
  payload: SavedViewCreatePayload,
): Promise<SavedViewResponse> {
  return apiPost<SavedViewResponse, SavedViewCreatePayload>(`${BASE}/`, payload);
}

export async function updateSavedView(
  id: string,
  payload: SavedViewUpdatePayload,
): Promise<SavedViewResponse> {
  return apiPatch<SavedViewResponse, SavedViewUpdatePayload>(
    `${BASE}/${id}/`,
    payload,
  );
}

export async function deleteSavedView(id: string): Promise<void> {
  await apiDelete<void>(`${BASE}/${id}/`);
}

export async function useSavedView(id: string): Promise<SavedViewResponse> {
  return apiPost<SavedViewResponse, Record<string, never>>(
    `${BASE}/${id}/use/`,
    {},
  );
}

export async function duplicateSavedView(id: string): Promise<SavedViewResponse> {
  return apiPost<SavedViewResponse, Record<string, never>>(
    `${BASE}/${id}/duplicate/`,
    {},
  );
}
