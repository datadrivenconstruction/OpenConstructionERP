// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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
  document_id: string | null;
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
  cde_state?: CDEState;
}

export interface TransitionPayload {
  target_state: CDEState;
  reason?: string;
  approver_signature?: string;
  approval_comments?: string;
}

export interface SuitabilityCodeEntry {
  code: string;
  label: string;
  state: CDEState;
}

export interface SuitabilityCodesResponse {
  codes: SuitabilityCodeEntry[];
  by_state: Record<CDEState, SuitabilityCodeEntry[]>;
}

export interface FunctionalRoleEntry {
  key: string;
  name: string;
  /** State-machine role this maps to (viewer / task_team_manager / lead_ap ...). */
  cde_role: string;
  /** Gate this role is accountable for (A / B), or null. */
  gate: string | null;
  acts_on: CDEState[];
  permissions: string[];
  summary: string;
}

export interface FunctionalRolesResponse {
  roles: FunctionalRoleEntry[];
  states: CDEState[];
  /** state -> role key -> short action label ("-" when the role is idle). */
  matrix: Record<string, Record<string, string>>;
}

export interface ReadinessSignalStatus {
  key: string;
  label: string;
  weight: number;
  hint: string;
  done: boolean;
}

export interface ReadinessNextAction {
  key: string;
  label: string;
  hint: string;
}

export type CDEReadinessLevel =
  | 'not_started'
  | 'forming'
  | 'operational'
  | 'mature';

export interface CDEReadiness {
  /** Weighted percent in [0, 100]. */
  score: number;
  level: CDEReadinessLevel;
  total_containers: number;
  signals: ReadinessSignalStatus[];
  next_actions: ReadinessNextAction[];
}

export interface StateTransitionEntry {
  id: string;
  container_id: string;
  from_state: CDEState;
  to_state: CDEState;
  gate_code: string | null;
  user_id: string | null;
  user_role: string | null;
  reason: string | null;
  signature: string | null;
  transitioned_at: string;
}

export interface ContainerTransmittalLink {
  transmittal_id: string;
  transmittal_number: string;
  subject: string;
  status: string;
  issued_date: string | null;
  revision_id: string | null;
  revision_code: string | null;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchCDEContainers(
  filters?: CDEContainerFilters,
): Promise<CDEContainer[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.state) params.set('state', filters.state);
  const qs = params.toString();
  // Trailing slash matches FastAPI route exactly — without it we hit a
  // 307 redirect that some proxies rewrite without forwarding the auth
  // header, which surfaces as an empty list in the UI.
  return apiGet<CDEContainer[]>(`/v1/cde/containers/${qs ? `?${qs}` : ''}`);
}

export async function createCDEContainer(
  data: CreateCDEContainerPayload,
): Promise<CDEContainer> {
  return apiPost<CDEContainer>('/v1/cde/containers/', data);
}

export async function transitionContainer(
  id: string,
  data: TransitionPayload,
): Promise<CDEContainer> {
  return apiPost<CDEContainer>(`/v1/cde/containers/${id}/transition/`, data);
}

export async function fetchContainerRevisions(id: string): Promise<CDERevision[]> {
  return apiGet<CDERevision[]>(`/v1/cde/containers/${id}/revisions/`);
}

export interface CreateRevisionPayload {
  file_name: string;
  change_summary?: string;
  /** Real storage key of a freshly-uploaded file (upload mode). */
  storage_key?: string;
  /** Existing Documents-hub row to link (link mode) — no duplicate is created. */
  document_id?: string;
  mime_type?: string;
  file_size?: string;
}

export async function createContainerRevision(
  containerId: string,
  data: CreateRevisionPayload,
): Promise<CDERevision> {
  return apiPost<CDERevision>(`/v1/cde/containers/${containerId}/revisions/`, data);
}

export async function fetchSuitabilityCodes(): Promise<SuitabilityCodesResponse> {
  return apiGet<SuitabilityCodesResponse>('/v1/cde/suitability-codes/');
}

export async function fetchFunctionalRoles(): Promise<FunctionalRolesResponse> {
  return apiGet<FunctionalRolesResponse>('/v1/cde/functional-roles/');
}

export interface CDEStats {
  total: number;
  by_state: Record<string, number>;
  by_discipline: Record<string, number>;
  latest_revisions: number;
}

export async function fetchCDEStats(projectId: string): Promise<CDEStats> {
  return apiGet<CDEStats>(`/v1/cde/stats/?project_id=${encodeURIComponent(projectId)}`);
}

export async function fetchCDEReadiness(projectId: string): Promise<CDEReadiness> {
  return apiGet<CDEReadiness>(
    `/v1/cde/readiness/?project_id=${encodeURIComponent(projectId)}`,
  );
}

export async function fetchContainerHistory(
  containerId: string,
): Promise<StateTransitionEntry[]> {
  return apiGet<StateTransitionEntry[]>(`/v1/cde/containers/${containerId}/history/`);
}

export async function fetchContainerTransmittals(
  containerId: string,
): Promise<ContainerTransmittalLink[]> {
  return apiGet<ContainerTransmittalLink[]>(
    `/v1/cde/containers/${containerId}/transmittals/`,
  );
}
