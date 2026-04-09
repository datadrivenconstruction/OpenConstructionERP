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

/* -- API Functions --------------------------------------------------------- */

export async function fetchInspections(filters?: InspectionFilters): Promise<Inspection[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.result) params.set('result', filters.result);
  const qs = params.toString();
  return apiGet<Inspection[]>(`/v1/inspections/${qs ? `?${qs}` : ''}`);
}

export async function createInspection(data: CreateInspectionPayload): Promise<Inspection> {
  return apiPost<Inspection>('/v1/inspections/', data);
}

export async function completeInspection(id: string): Promise<Inspection> {
  return apiPost<Inspection>(`/v1/inspections/${id}/complete/`);
}
