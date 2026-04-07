/**
 * API helpers for Common Data Environment (CDE) — ISO 19650.
 *
 * All endpoints are prefixed with /v1/cde/.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type CDEState = 'wip' | 'shared' | 'published' | 'archived';

export type CDEDiscipline =
  | 'architecture'
  | 'structural'
  | 'mep'
  | 'civil'
  | 'landscape'
  | 'interior'
  | 'other';

export interface CDERevision {
  id: string;
  container_id: string;
  revision_code: string;
  revision_number: number;
  is_preliminary: boolean;
  status: string;
  file_name: string;
  file_size: string | null;
  mime_type: string | null;
  storage_key: string | null;
  content_hash: string | null;
  change_summary: string | null;
  approved_by: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CDEContainer {
  id: string;
  project_id: string;
  container_code: string;
  title: string;
  description: string | null;
  discipline_code: CDEDiscipline | string | null;
  cde_state: CDEState;
  suitability_code: string | null;
  current_revision_id: string | null;
  classification_code: string | null;
  classification_system: string | null;
  originator_code: string | null;
  security_classification: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CDEContainerFilters {
  project_id?: string;
  state?: CDEState | '';
}

export interface CreateCDEContainerPayload {
  project_id: string;
  container_code: string;
  title: string;
  discipline_code?: CDEDiscipline | string;
  suitability_code?: string;
  classification_code?: string;
  classification_system?: string;
  description?: string;
}

export interface TransitionPayload {
  target_state: CDEState;
  comments?: string;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchCDEContainers(
  filters?: CDEContainerFilters,
): Promise<CDEContainer[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.state) params.set('state', filters.state);
  const qs = params.toString();
  return apiGet<CDEContainer[]>(`/v1/cde/containers${qs ? `?${qs}` : ''}`);
}

export async function createCDEContainer(
  data: CreateCDEContainerPayload,
): Promise<CDEContainer> {
  return apiPost<CDEContainer>('/v1/cde/containers', data);
}

export async function transitionContainer(
  id: string,
  data: TransitionPayload,
): Promise<CDEContainer> {
  return apiPost<CDEContainer>(`/v1/cde/containers/${id}/transition`, data);
}

export async function fetchContainerRevisions(id: string): Promise<CDERevision[]> {
  return apiGet<CDERevision[]>(`/v1/cde/containers/${id}/revisions`);
}
