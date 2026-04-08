/**
 * Takeoff Measurements API client.
 *
 * Mirrors backend endpoints at /v1/takeoff/measurements/*.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ────────────────────────────────────────────────────────────── */

export interface MeasurementPoint {
  x: number;
  y: number;
}

export interface MeasurementCreate {
  project_id: string;
  document_id?: string | null;
  page: number;
  type: string;
  group_name?: string;
  group_color?: string;
  annotation?: string | null;
  points: MeasurementPoint[];
  measurement_value?: number | null;
  measurement_unit?: string;
  depth?: number | null;
  volume?: number | null;
  perimeter?: number | null;
  count_value?: number | null;
  scale_pixels_per_unit?: number | null;
  linked_boq_position_id?: string | null;
  metadata?: Record<string, unknown>;
}

export interface MeasurementResponse {
  id: string;
  project_id: string;
  document_id: string | null;
  page: number;
  type: string;
  group_name: string;
  group_color: string;
  annotation: string | null;
  points: MeasurementPoint[];
  measurement_value: number | null;
  measurement_unit: string;
  depth: number | null;
  volume: number | null;
  perimeter: number | null;
  count_value: number | null;
  scale_pixels_per_unit: number | null;
  linked_boq_position_id: string | null;
  metadata: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface MeasurementSummary {
  total_measurements: number;
  by_type: Record<string, number>;
  by_group: Record<string, number>;
}

/* ── API functions ────────────────────────────────────────────────────── */

export const takeoffApi = {
  /** List measurements for a project, optionally filtered by document. */
  list: (projectId: string, documentId?: string) => {
    let url = `/v1/takeoff/measurements?project_id=${projectId}`;
    if (documentId) url += `&document_id=${encodeURIComponent(documentId)}`;
    return apiGet<MeasurementResponse[]>(url);
  },

  /** Create a single measurement. */
  create: (data: MeasurementCreate) =>
    apiPost<MeasurementResponse>('/v1/takeoff/measurements', data),

  /** Bulk create measurements (up to 500). */
  bulkCreate: (measurements: MeasurementCreate[]) =>
    apiPost<MeasurementResponse[]>('/v1/takeoff/measurements/bulk', { measurements }),

  /** Update a measurement. */
  update: (id: string, data: Partial<MeasurementCreate>) =>
    apiPatch<MeasurementResponse>(`/v1/takeoff/measurements/${id}`, data),

  /** Delete a measurement. */
  delete: (id: string) =>
    apiDelete(`/v1/takeoff/measurements/${id}`),

  /** Link a measurement to a BOQ position. */
  linkToBoq: (id: string, boqPositionId: string) =>
    apiPost<MeasurementResponse>(`/v1/takeoff/measurements/${id}/link-to-boq`, {
      boq_position_id: boqPositionId,
    }),

  /** Get measurement summary stats for a project. */
  summary: (projectId: string) =>
    apiGet<MeasurementSummary>(`/v1/takeoff/measurements/summary?project_id=${projectId}`),

  /** Export measurements as CSV or JSON. */
  export: (projectId: string, format: 'csv' | 'json' = 'json') =>
    apiGet<unknown>(`/v1/takeoff/measurements/export?project_id=${projectId}&format=${format}`),

  /** Save a CAD takeoff session to a project as a BIM model. */
  saveToProject: (
    sessionId: string,
    projectId: string,
    modelName: string = 'Imported from Takeoff',
  ) =>
    apiPost<{ model_id: string; element_count: number; model_name: string; project_id: string }>(
      `/v1/takeoff/sessions/${sessionId}/save-to-project?project_id=${encodeURIComponent(projectId)}`,
      { model_name: modelName },
    ),
};
