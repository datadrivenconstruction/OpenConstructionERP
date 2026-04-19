/**
 * API helpers for Quality Inspections.
 *
 * All endpoints are prefixed with /v1/inspections/.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

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

export type InspectionStatus = 'scheduled' | 'in_progress' | 'completed' | 'cancelled';

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
  inspection_number: number;
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
  created_at: string;
  updated_at: string;
}

export interface InspectionFilters {
  project_id?: string;
  status?: InspectionStatus | '';
  result?: InspectionResult | '';
}

export interface CreateInspectionPayload {
  project_id: string;
  title: string;
  inspection_type: InspectionType;
  inspection_date?: string;
  inspector_id?: string;
  location?: string;
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
  date?: string;
  inspection_date?: string | null;
  checklist?: ChecklistEntryWire[];
  checklist_data?: ChecklistEntryWire[];
};

function normaliseChecklistItem(e: ChecklistEntryWire, i: number): ChecklistItem {
  const passed =
    typeof e.passed === 'boolean'
      ? e.passed
      : e.response === 'pass' || e.response === 'yes' || e.response === 'true';
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
    inspector: raw.inspector ?? raw.inspector_id ?? '',
    date: raw.date ?? raw.inspection_date ?? '',
    checklist: checklistSrc.map(normaliseChecklistItem),
    notes: raw.notes ?? '',
  } as Inspection;
}

/* -- API Functions --------------------------------------------------------- */

export async function fetchInspections(filters?: InspectionFilters): Promise<Inspection[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.result) params.set('result', filters.result);
  const qs = params.toString();
  const rows = await apiGet<InspectionWire[]>(`/v1/inspections/${qs ? `?${qs}` : ''}`);
  return rows.map(normaliseInspection);
}

export async function createInspection(data: CreateInspectionPayload): Promise<Inspection> {
  const row = await apiPost<InspectionWire>('/v1/inspections/', data);
  return normaliseInspection(row);
}

export async function completeInspection(id: string): Promise<Inspection> {
  const row = await apiPost<InspectionWire>(`/v1/inspections/${id}/complete/`);
  return normaliseInspection(row);
}
