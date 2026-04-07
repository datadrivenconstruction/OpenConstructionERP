/**
 * API helpers for BIM Hub.
 *
 * Endpoints:
 *   GET /v1/bim_hub?project_id=X         — list models for a project
 *   GET /v1/bim_hub/models/{id}/elements  — list elements for a model
 */

import { apiGet } from '@/shared/lib/api';
import type { BIMElementData, BIMModelData } from '@/shared/ui/BIMViewer';

/* ── Response Types ────────────────────────────────────────────────────── */

export interface BIMModelsResponse {
  models: BIMModelData[];
  total: number;
}

export interface BIMElementsResponse {
  elements: BIMElementData[];
  total: number;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

/** Fetch all BIM models for a project. */
export async function fetchBIMModels(projectId: string): Promise<BIMModelsResponse> {
  return apiGet<BIMModelsResponse>(`/v1/bim_hub?project_id=${encodeURIComponent(projectId)}`);
}

/** Fetch elements for a specific BIM model. */
export async function fetchBIMElements(
  modelId: string,
  limit = 1000,
  offset = 0,
): Promise<BIMElementsResponse> {
  return apiGet<BIMElementsResponse>(
    `/v1/bim_hub/models/${encodeURIComponent(modelId)}/elements?limit=${limit}&offset=${offset}`,
  );
}
