/**
 * API helpers for Requests for Information (RFI).
 *
 * All endpoints are prefixed with /v1/rfi/.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type RFIStatus = 'draft' | 'open' | 'answered' | 'closed' | 'void';

export interface RFI {
  id: string;
  project_id: string;
  rfi_number: string;
  subject: string;
  question: string;
  official_response: string | null;
  status: RFIStatus;
  raised_by: string;
  assigned_to: string | null;
  ball_in_court: string | null;
  responded_by: string | null;
  responded_at: string | null;
  cost_impact: boolean;
  cost_impact_value: string | null;
  schedule_impact: boolean;
  schedule_impact_days: number | null;
  date_required: string | null;
  response_due_date: string | null;
  linked_drawing_ids: string[];
  change_order_id: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  is_overdue: boolean;
  days_open: number;
}

export interface RFIFilters {
  project_id?: string;
  status?: RFIStatus | '';
}

export interface CreateRFIPayload {
  project_id: string;
  subject: string;
  question: string;
  ball_in_court?: string;
  response_due_date?: string;
  cost_impact?: boolean;
  schedule_impact?: boolean;
  linked_drawing_ids?: string[];
}

export interface RespondRFIPayload {
  official_response: string;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchRFIs(filters?: RFIFilters): Promise<RFI[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  const qs = params.toString();
  return apiGet<RFI[]>(`/v1/rfi/${qs ? `?${qs}` : ''}`);
}

export async function createRFI(data: CreateRFIPayload): Promise<RFI> {
  return apiPost<RFI>('/v1/rfi/', data);
}

export async function respondToRFI(id: string, data: RespondRFIPayload): Promise<RFI> {
  return apiPost<RFI>(`/v1/rfi/${id}/respond/`, data);
}

export async function closeRFI(id: string): Promise<RFI> {
  return apiPost<RFI>(`/v1/rfi/${id}/close/`);
}
