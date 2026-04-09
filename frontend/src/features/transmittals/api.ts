/**
 * API helpers for Transmittals.
 *
 * All endpoints are prefixed with /v1/transmittals/.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type TransmittalStatus = 'draft' | 'issued' | 'acknowledged' | 'closed';

export type TransmittalPurpose =
  | 'for_approval'
  | 'for_information'
  | 'for_construction'
  | 'for_review'
  | 'for_record'
  | 'as_requested';

export interface TransmittalRecipient {
  id: string;
  name: string;
  company: string | null;
  acknowledged: boolean;
  acknowledged_at: string | null;
  response: string | null;
}

export interface TransmittalItem {
  id: string;
  document_title: string;
  document_ref: string | null;
  revision: string | null;
}

export interface Transmittal {
  id: string;
  project_id: string;
  transmittal_number: string;
  subject: string;
  purpose: TransmittalPurpose;
  status: TransmittalStatus;
  cover_note: string | null;
  issued_date: string | null;
  response_due: string | null;
  locked: boolean;
  recipients: TransmittalRecipient[];
  items: TransmittalItem[];
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface TransmittalFilters {
  project_id?: string;
  status?: TransmittalStatus | '';
}

export interface CreateTransmittalPayload {
  project_id: string;
  subject: string;
  purpose_code: TransmittalPurpose;
  cover_note?: string;
  response_due_date?: string;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchTransmittals(filters?: TransmittalFilters): Promise<Transmittal[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  const qs = params.toString();
  return apiGet<Transmittal[]>(`/v1/transmittals${qs ? `?${qs}` : ''}`);
}

export async function createTransmittal(data: CreateTransmittalPayload): Promise<Transmittal> {
  return apiPost<Transmittal>('/v1/transmittals/', data);
}

export async function issueTransmittal(id: string): Promise<Transmittal> {
  return apiPost<Transmittal>(`/v1/transmittals/${id}/issue`);
}
