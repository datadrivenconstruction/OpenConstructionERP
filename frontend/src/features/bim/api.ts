/**
 * API helpers for BIM Hub.
 *
 * Endpoints:
 *   GET  /v1/bim_hub?project_id=X          — list models for a project
 *   POST /v1/bim_hub/upload                 — upload BIM data (DataFrame + optional DAE)
 *   GET  /v1/bim_hub/models/{id}/elements   — list elements for a model
 *   GET  /v1/bim_hub/models/{id}/geometry   — serve DAE geometry file
 */

import { apiGet, apiDelete } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import type { BIMElementData, BIMModelData } from '@/shared/ui/BIMViewer';

/* ── Response Types ────────────────────────────────────────────────────── */

export interface BIMModelsResponse {
  items: BIMModelData[];
  total: number;
}

export interface BIMElementsResponse {
  items: BIMElementData[];
  total: number;
}

export interface BIMUploadResponse {
  model_id: string;
  element_count: number;
  storeys: string[];
  disciplines: string[];
  has_geometry: boolean;
}

export interface BIMCadUploadResponse {
  model_id: string;
  name: string;
  format: string;
  file_size: number;
  status: string;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

/** Fetch all BIM models for a project. */
export async function fetchBIMModels(projectId: string): Promise<BIMModelsResponse> {
  return apiGet<BIMModelsResponse>(`/v1/bim_hub/?project_id=${encodeURIComponent(projectId)}`);
}

/** Fetch a single BIM model by ID (used for status polling). */
export async function fetchBIMModel(modelId: string): Promise<BIMModelData> {
  return apiGet<BIMModelData>(`/v1/bim_hub/${encodeURIComponent(modelId)}`);
}

/** Fetch elements for a specific BIM model. */
export async function fetchBIMElements(
  modelId: string,
  limit = 1000,
  offset = 0,
): Promise<BIMElementsResponse> {
  return apiGet<BIMElementsResponse>(
    `/v1/bim_hub/models/${encodeURIComponent(modelId)}/elements/?limit=${limit}&offset=${offset}`,
  );
}

/** Get the geometry file URL for a BIM model. */
export function getGeometryUrl(modelId: string): string {
  return `/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/geometry`;
}

/** Upload BIM data (DataFrame + optional geometry file). */
export async function uploadBIMData(
  projectId: string,
  name: string,
  discipline: string,
  dataFile: File,
  geometryFile?: File | null,
): Promise<BIMUploadResponse> {
  const formData = new FormData();
  formData.append('data_file', dataFile);
  if (geometryFile) {
    formData.append('geometry_file', geometryFile);
  }

  const params = new URLSearchParams({
    project_id: projectId,
    name,
    discipline,
  });

  const token = useAuthStore.getState().accessToken;
  const headers: HeadersInit = {
    Accept: 'application/json',
    'X-DDC-Client': 'OE/1.0',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`/api/v1/bim_hub/upload/?${params.toString()}`, {
      method: 'POST',
      headers,
      body: formData,
    });
  } catch (networkErr) {
    throw new Error(
      'Cannot connect to server. Please check that the backend is running and try again.',
    );
  }

  if (!response.ok) {
    let detail = `Upload failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse errors
    }
    throw new Error(detail);
  }

  return response.json();
}

/** Delete a BIM model and all its elements. */
export async function deleteBIMModel(modelId: string): Promise<void> {
  await apiDelete(`/v1/bim_hub/${encodeURIComponent(modelId)}`);
}

/** Upload a raw CAD file (RVT, IFC, DWG, DGN, FBX, OBJ, 3DS) for background processing. */
export async function uploadCADFile(
  projectId: string,
  name: string,
  discipline: string,
  file: File,
): Promise<BIMCadUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const params = new URLSearchParams({
    project_id: projectId,
    name,
    discipline,
  });

  const token = useAuthStore.getState().accessToken;
  const headers: HeadersInit = {
    Accept: 'application/json',
    'X-DDC-Client': 'OE/1.0',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`/api/v1/bim_hub/upload-cad/?${params.toString()}`, {
      method: 'POST',
      headers,
      body: formData,
    });
  } catch (networkErr) {
    throw new Error(
      'Cannot connect to server. Please check that the backend is running and try again.',
    );
  }

  if (!response.ok) {
    let detail = `Upload failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse errors
    }
    throw new Error(detail);
  }

  return response.json();
}
