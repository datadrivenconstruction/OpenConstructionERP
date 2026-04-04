/**
 * API helpers for Requirements & Quality Gates.
 *
 * All endpoints are prefixed with /v1/requirements/.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export interface Requirement {
  id: string;
  requirement_set_id: string;
  entity: string;
  attribute: string;
  constraint_type: string;
  constraint_value: string;
  unit: string;
  category: string;
  priority: string;
  status: string;
  confidence: number | null;
  source_ref: string;
  notes: string;
  linked_position_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface RequirementSet {
  id: string;
  project_id: string;
  name: string;
  description: string;
  source_type: string;
  source_filename: string;
  status: string;
  gate_status: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface GateResult {
  id: string;
  requirement_set_id: string;
  gate_number: number;
  gate_name: string;
  status: 'pass' | 'fail' | 'warning' | 'pending' | 'skipped';
  score: number;
  findings: Array<Record<string, unknown>>;
  created_at: string;
}

export interface RequirementSetDetail extends RequirementSet {
  requirements: Requirement[];
  gate_results: GateResult[];
}

export interface RequirementStats {
  total_requirements: number;
  total_sets: number;
  by_priority: Record<string, number>;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  linked_count: number;
  unlinked_count: number;
}

export interface CreateRequirementSetPayload {
  project_id: string;
  name: string;
  description?: string;
}

export interface AddRequirementPayload {
  entity: string;
  attribute: string;
  constraint_type: string;
  constraint_value: string;
  unit: string;
  category: string;
  priority: string;
  source_ref?: string;
  notes?: string;
}

export interface UpdateRequirementPayload {
  entity?: string;
  attribute?: string;
  constraint_type?: string;
  constraint_value?: string;
  unit?: string;
  category?: string;
  priority?: string;
  source_ref?: string;
  notes?: string;
  status?: string;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchRequirementSets(projectId: string): Promise<RequirementSet[]> {
  return apiGet<RequirementSet[]>(`/v1/requirements/?project_id=${projectId}`);
}

export async function fetchRequirementSetDetail(setId: string): Promise<RequirementSetDetail> {
  return apiGet<RequirementSetDetail>(`/v1/requirements/${setId}`);
}

export async function fetchRequirementStats(projectId: string): Promise<RequirementStats> {
  return apiGet<RequirementStats>(`/v1/requirements/stats?project_id=${projectId}`);
}

export async function createRequirementSet(
  data: CreateRequirementSetPayload,
): Promise<RequirementSet> {
  return apiPost<RequirementSet>('/v1/requirements/', data);
}

export async function deleteRequirementSet(setId: string): Promise<void> {
  return apiDelete(`/v1/requirements/${setId}`);
}

export async function addRequirement(
  setId: string,
  data: AddRequirementPayload,
): Promise<Requirement> {
  return apiPost<Requirement>(`/v1/requirements/${setId}/requirements`, data);
}

export async function updateRequirement(
  setId: string,
  reqId: string,
  data: UpdateRequirementPayload,
): Promise<Requirement> {
  return apiPatch<Requirement>(`/v1/requirements/${setId}/requirements/${reqId}`, data);
}

export async function deleteRequirement(setId: string, reqId: string): Promise<void> {
  return apiDelete(`/v1/requirements/${setId}/requirements/${reqId}`);
}

export async function runGate(setId: string, gateNumber: number): Promise<GateResult> {
  return apiPost<GateResult>(`/v1/requirements/${setId}/gates/${gateNumber}/run`);
}

export async function fetchGates(setId: string): Promise<GateResult[]> {
  return apiGet<GateResult[]>(`/v1/requirements/${setId}/gates`);
}

export async function linkToPosition(
  setId: string,
  reqId: string,
  positionId: string,
): Promise<Requirement> {
  return apiPost<Requirement>(
    `/v1/requirements/${setId}/requirements/${reqId}/link/${positionId}`,
  );
}

export async function importFromText(setId: string, text: string): Promise<RequirementSetDetail> {
  return apiPost<RequirementSetDetail>(`/v1/requirements/${setId}/import/text`, { text });
}
