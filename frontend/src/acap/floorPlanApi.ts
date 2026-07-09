/**
 * API client for the ACAP layout editor.
 *
 * Uses the shared typed fetch helpers (@/shared/lib/api) - `apiGet`/`apiPut`
 * already prepend the '/api' base, so paths here start at '/v1/acap' (see
 * frontend/src/features/cde/api.ts for the same convention).
 */

import { apiGet, apiPut, ApiError } from '@/shared/lib/api';
import type { FloorPlan } from './planTypes';

const PREFIX = '/v1/acap';

export interface LayoutGetResponse {
  version: number;
  status: string;
  plan: FloorPlan;
}

export interface LayoutSaveResponse {
  version: number;
  plan: FloorPlan;
}

/** Thrown when the server rejects a save with geometric validation reasons (422). */
export class LayoutValidationApiError extends Error {
  constructor(public readonly reasons: string[]) {
    super('Layout invalid');
    this.name = 'LayoutValidationApiError';
  }
}

/** Fetch the latest saved layout for a project. Throws ApiError(404) if none exists. */
export function getLatestLayout(projectId: string): Promise<LayoutGetResponse> {
  return apiGet<LayoutGetResponse>(`${PREFIX}/projects/${projectId}/layout`);
}

/** Save an edited layout as a new version. Throws LayoutValidationApiError on 422. */
export async function saveLayout(projectId: string, plan: FloorPlan): Promise<LayoutSaveResponse> {
  try {
    return await apiPut<LayoutSaveResponse, FloorPlan>(`${PREFIX}/projects/${projectId}/layout`, plan);
  } catch (err) {
    if (err instanceof ApiError && err.status === 422) {
      const body = err.body as { detail?: { reasons?: string[] } } | undefined;
      const reasons = body?.detail?.reasons;
      if (Array.isArray(reasons)) throw new LayoutValidationApiError(reasons);
    }
    throw err;
  }
}
