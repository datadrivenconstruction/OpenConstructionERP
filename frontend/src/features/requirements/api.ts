/**
 * API helpers for Requirements & Quality Gates.
 *
 * All endpoints are prefixed with /v1/requirements/.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

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
  if (!projectId) return [];
  const res = await apiGet<RequirementSet[] | { items: RequirementSet[] }>(
    `/v1/requirements/?project_id=${projectId}`,
  );
  return Array.isArray(res) ? res : res.items ?? [];
}

export async function fetchRequirementSetDetail(setId: string): Promise<RequirementSetDetail> {
  return apiGet<RequirementSetDetail>(`/v1/requirements/${setId}`);
}

export async function fetchRequirementStats(projectId: string): Promise<RequirementStats> {
  if (!projectId) return { total_requirements: 0, total_sets: 0, by_priority: {}, by_status: {}, by_category: {}, linked_count: 0, unlinked_count: 0 };
  return apiGet<RequirementStats>(`/v1/requirements/stats/?project_id=${projectId}`);
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
  const res = await apiGet<GateResult[] | { items: GateResult[] }>(
    `/v1/requirements/${setId}/gates`,
  );
  return Array.isArray(res) ? res : res.items ?? [];
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

/* ── Export Functions ─────────────────────────────────────────────────────── */

const EXPORT_COLUMNS = [
  'entity',
  'attribute',
  'constraint_type',
  'constraint_value',
  'unit',
  'category',
  'priority',
  'status',
  'confidence',
  'source_ref',
  'notes',
] as const;

/**
 * Export requirements as CSV.
 * Tries the backend endpoint first; falls back to client-side generation.
 */
export async function exportRequirementsCSV(
  setId: string,
  requirements?: Requirement[],
): Promise<Blob> {
  try {
    const res = await fetch(`/api/v1/requirements/${setId}/export/?format=csv`, {
      headers: {
        Authorization: `Bearer ${useAuthStore.getState().accessToken ?? ''}`,
        'X-DDC-Client': 'OE/1.0',
      },
    });
    if (res.ok) {
      return await res.blob();
    }
  } catch {
    // fall through to client-side
  }

  // Client-side fallback
  const reqs = requirements ?? (await fetchRequirementSetDetail(setId)).requirements;
  const header = EXPORT_COLUMNS.join(',');
  const rows = reqs.map((r) =>
    EXPORT_COLUMNS.map((col) => {
      const val = String(r[col as keyof Requirement] ?? '');
      // Escape CSV values containing commas, quotes, or newlines
      if (val.includes(',') || val.includes('"') || val.includes('\n')) {
        return `"${val.replace(/"/g, '""')}"`;
      }
      return val;
    }).join(','),
  );
  const csv = [header, ...rows].join('\n');
  return new Blob([csv], { type: 'text/csv;charset=utf-8' });
}

/**
 * Export requirements as Excel (CSV with .xlsx-friendly formatting).
 * Uses CSV with BOM for Excel compatibility.
 */
export async function exportRequirementsExcel(
  setId: string,
  requirements?: Requirement[],
): Promise<Blob> {
  const reqs = requirements ?? (await fetchRequirementSetDetail(setId)).requirements;
  const header = EXPORT_COLUMNS.join('\t');
  const rows = reqs.map((r) =>
    EXPORT_COLUMNS.map((col) => {
      const val = String(r[col as keyof Requirement] ?? '');
      return val.replace(/\t/g, ' ');
    }).join('\t'),
  );
  const tsv = '\uFEFF' + [header, ...rows].join('\n');
  return new Blob([tsv], {
    type: 'application/vnd.ms-excel;charset=utf-8',
  });
}

/**
 * Export requirements as formatted JSON string.
 */
export async function exportRequirementsJSON(
  setId: string,
  requirements?: Requirement[],
): Promise<string> {
  const reqs = requirements ?? (await fetchRequirementSetDetail(setId)).requirements;
  const data = reqs.map((r) => {
    const obj: Record<string, unknown> = {};
    for (const col of EXPORT_COLUMNS) {
      obj[col] = r[col as keyof Requirement] ?? '';
    }
    return obj;
  });
  return JSON.stringify(data, null, 2);
}

