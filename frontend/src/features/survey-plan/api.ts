// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Plan canvas endpoints of survey_core: view transform, codes, settings, edits, points, sketch. */

import { apiGet, apiPost, apiPut } from '@/shared/lib/api';
import type { CodeEntry } from './engine/linework';
import type { EditOp, PlanFeature, ViewTransformDTO } from './types';
import type { PlanConventions } from './units/conventions';

const base = '/v1/survey-core';

export interface CodeLibraryOut {
  items: CodeEntry[];
  /** `project` when the project overrides the pack default. */
  source: 'project' | 'pack' | 'neutral';
  countries: string[];
}

export interface PlanSettingsOut {
  /** Effective conventions: project override over the country default. */
  conventions: PlanConventions;
  defaults: PlanConventions;
  source: 'project' | 'country' | 'neutral';
  country: string | null;
  /** Combined scale factor at the project centre, null for a local grid. */
  csf: number | null;
}

export interface PlanPointOut {
  id: string;
  point_id: string;
  e: number;
  n: number;
  z: number | null;
  code: string;
  kind: string;
  source_line: number | null;
  rev: number;
}

export interface EditRow {
  id: string;
  entity_type: string;
  entity_id: string;
  rev: number;
  op: 'create' | 'update' | 'delete' | 'revert';
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  author: string | null;
  author_name: string;
  created_at: string;
  note: string;
  summary: string;
}

export interface SaveResult {
  client_id: string;
  entity_type: string;
  entity_id: string;
  rev: number;
  edit_id: string;
}

/** Body of a 409: who changed the record since the client read it. */
export interface ConflictDetail {
  code: 'stale_rev';
  entity_type: string;
  entity_id: string;
  current_rev: number;
  author_name: string;
  changed_at: string;
  current: Record<string, unknown> | null;
}

export const planApi = {
  viewTransform: (projectId: string) => apiGet<ViewTransformDTO>(`${base}/projects/${projectId}/view-transform`),
  codes: (projectId: string) => apiGet<CodeLibraryOut>(`${base}/projects/${projectId}/codes`),
  putCodes: (projectId: string, items: CodeEntry[] | null) =>
    apiPut<CodeLibraryOut>(`${base}/projects/${projectId}/codes`, { items }),
  settings: (projectId: string) => apiGet<PlanSettingsOut>(`${base}/projects/${projectId}/plan-settings`),
  putSettings: (projectId: string, conventions: Partial<PlanConventions> | null) =>
    apiPut<PlanSettingsOut>(`${base}/projects/${projectId}/plan-settings`, { conventions }),
  points: (projectId: string) => apiGet<{ items: PlanPointOut[] }>(`${base}/projects/${projectId}/plan-points`),
  sketch: (projectId: string) => apiGet<{ features: PlanFeature[] }>(`${base}/projects/${projectId}/sketch`),
  edits: (projectId: string, entityType?: string, entityId?: string) => {
    const q = new URLSearchParams();
    if (entityType) q.set('entity_type', entityType);
    if (entityId) q.set('entity_id', entityId);
    const qs = q.toString();
    return apiGet<{ items: EditRow[] }>(`${base}/projects/${projectId}/edits${qs ? `?${qs}` : ''}`);
  },
  save: (projectId: string, ops: EditOp[]) => apiPost<{ items: SaveResult[] }>(`${base}/projects/${projectId}/edits`, { ops }),
  restore: (editId: string) => apiPost<SaveResult>(`${base}/edits/${editId}/restore`, {}),
};

export const planKeys = {
  all: (projectId: string) => ['survey-plan', projectId] as const,
  viewTransform: (projectId: string) => ['survey-plan', projectId, 'view-transform'] as const,
  codes: (projectId: string) => ['survey-plan', projectId, 'codes'] as const,
  settings: (projectId: string) => ['survey-plan', projectId, 'settings'] as const,
  points: (projectId: string) => ['survey-plan', projectId, 'points'] as const,
  sketch: (projectId: string) => ['survey-plan', projectId, 'sketch'] as const,
  edits: (projectId: string, entityType?: string, entityId?: string) =>
    ['survey-plan', projectId, 'edits', entityType ?? '', entityId ?? ''] as const,
};
