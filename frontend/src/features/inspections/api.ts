// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Quality Inspections.
 *
 * All endpoints are prefixed with /v1/inspections/.
 */

import { apiGet, apiPost, apiPatch, apiDelete, type Page } from '@/shared/lib/api';

/* -- Types ----------------------------------------------------------------- */

export type InspectionType =
  | 'structural'
  | 'electrical'
  | 'plumbing'
  | 'fire_safety'
  | 'concrete'
  | 'concrete_pour'
  | 'waterproofing'
  | 'mep'
  | 'fire_stopping'
  | 'handover'
  | 'general';

export type InspectionResult = 'pass' | 'fail' | 'partial';

export type InspectionStatus =
  | 'scheduled'
  | 'in_progress'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface ChecklistItem {
  id: string;
  description: string;
  passed: boolean;
  critical: boolean;
  notes: string;
}

export interface Inspection {
  id: string;
  project_id: string;
  /** Backend returns this already formatted, e.g. "INS-001". Do not re-prefix. */
  inspection_number: string;
  title: string;
  inspection_type: InspectionType;
  inspector: string;
  date: string;
  location: string;
  result: InspectionResult | null;
  status: InspectionStatus;
  checklist: ChecklistItem[];
  notes: string;
  created_by: string | null;
  /** Optimistic-lock counter; sent back as `If-Match` on update. */
  version?: number;
  created_at: string;
  updated_at: string;
}

export interface InspectionFilters {
  project_id?: string;
  status?: InspectionStatus | '';
  result?: InspectionResult | '';
  type?: InspectionType | '';
}

/**
 * Checklist item as sent to the backend (matches the `ChecklistEntry`
 * schema). The backend keys off `question` and the boolean `passed`
 * (the create-defect / create-ncr flows read failed items from here).
 */
export interface ChecklistEntryPayload {
  question: string;
  response_type?: string;
  passed?: boolean;
  critical?: boolean;
  notes?: string;
}

export interface CreateInspectionPayload {
  project_id: string;
  title: string;
  inspection_type: InspectionType;
  inspection_date?: string;
  inspector_id?: string;
  location?: string;
  checklist_data?: ChecklistEntryPayload[];
  /** Idempotency key: a replayed create returns the first row. */
  client_op_id?: string;
}

export interface UpdateInspectionPayload {
  title?: string;
  inspection_type?: InspectionType;
  inspection_date?: string | null;
  inspector_id?: string | null;
  location?: string | null;
  status?: InspectionStatus;
  checklist_data?: ChecklistEntryPayload[];
}

/** Result returned by POST /{id}/create-ncr/. */
export interface CreateNcrResult {
  ncr_id: string;
  ncr_number: string;
  inspection_id: string;
  severity?: string;
  ncr_type?: string;
  /** false when an NCR already linked to this inspection was returned as-is. */
  created: boolean;
}

/* -- Wire <-> UI normaliser ----------------------------------------------- */

type ChecklistEntryWire = {
  id?: string;
  category?: string | null;
  question?: string;
  response_type?: string;
  response?: string | null;
  critical?: boolean;
  description?: string;
  passed?: boolean;
  notes?: string | null;
};

type InspectionWire = Omit<Inspection, 'inspector' | 'date' | 'checklist'> & {
  inspector?: string;
  inspector_id?: string | null;
  inspector_name?: string | null;
  date?: string;
  inspection_date?: string | null;
  checklist?: ChecklistEntryWire[];
  checklist_data?: ChecklistEntryWire[];
};

function normaliseChecklistItem(e: ChecklistEntryWire, i: number): ChecklistItem {
  // Mirror the backend's `_is_failed`: an item only counts as failed when it
  // carries an explicit failing signal. An absent/empty response means "not yet
  // assessed", which we treat as not-failed so freshly created checklists do not
  // render as a wall of red crosses.
  const failResponses = new Set(['no', 'fail', 'false', '0', 'failed']);
  const resp = (e.response ?? '').trim().toLowerCase();
  const passed = typeof e.passed === 'boolean' ? e.passed : !failResponses.has(resp);
  return {
    id: e.id ?? `item-${i}`,
    description: e.description ?? e.question ?? '',
    passed,
    critical: Boolean(e.critical),
    notes: e.notes ?? '',
  };
}

function normaliseInspection(raw: InspectionWire): Inspection {
  const checklistSrc = raw.checklist ?? raw.checklist_data ?? [];
  return {
    ...raw,
    // ``inspector_name`` is the backend's resolution of ``inspector_id``, which
    // may hold a contact id, a user id or a typed name depending on who wrote
    // the row. It is absent when nothing resolved, and then the stored value is
    // the best thing to show: on a hand-typed row it is already the name, and
    // on a deleted party it is the only trace left. Showing the id unresolved
    // is what printed a bare UUID in the inspector column.
    inspector: raw.inspector_name ?? raw.inspector ?? raw.inspector_id ?? '',
    date: raw.date ?? raw.inspection_date ?? '',
    checklist: checklistSrc.map(normaliseChecklistItem),
    notes: raw.notes ?? '',
  } as Inspection;
}

/* -- API Functions --------------------------------------------------------- */

export async function fetchInspections(
  filters?: InspectionFilters,
): Promise<Page<Inspection>> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.result) params.set('result', filters.result);
  if (filters?.type) params.set('type', filters.type);
  const qs = params.toString();
  const page = await apiGet<Page<InspectionWire>>(`/v1/inspections/${qs ? `?${qs}` : ''}`);
  return { ...page, items: page.items.map(normaliseInspection) };
}

export async function createInspection(data: CreateInspectionPayload): Promise<Inspection> {
  const row = await apiPost<InspectionWire>('/v1/inspections/', data);
  return normaliseInspection(row);
}

export async function completeInspection(
  id: string,
  result: InspectionResult = 'pass',
): Promise<Inspection> {
  const row = await apiPost<InspectionWire>(`/v1/inspections/${id}/complete/`, { result });
  return normaliseInspection(row);
}

/**
 * Raise a Non-Conformance Report pre-filled from a failed/partial inspection.
 *
 * The backend (POST /v1/inspections/{id}/create-ncr/) pre-fills the title and
 * description from failed checklist items, maps severity + ncr_type, and links
 * `linked_inspection_id`. It is idempotent: if an NCR already exists for the
 * inspection it is returned with `created: false`.
 */
export async function createNcrFromInspection(id: string): Promise<CreateNcrResult> {
  return apiPost<CreateNcrResult>(`/v1/inspections/${id}/create-ncr/`, {});
}

export async function updateInspection(
  id: string,
  data: UpdateInspectionPayload,
  version?: number,
): Promise<Inspection> {
  const row =
    version === undefined
      ? await apiPatch<InspectionWire>(`/v1/inspections/${id}`, data)
      : await apiPatch<InspectionWire>(
          `/v1/inspections/${id}`,
          { ...data, version },
          { headers: { 'If-Match': String(version) } },
        );
  return normaliseInspection(row);
}

export async function deleteInspection(id: string): Promise<void> {
  return apiDelete(`/v1/inspections/${id}`);
}
