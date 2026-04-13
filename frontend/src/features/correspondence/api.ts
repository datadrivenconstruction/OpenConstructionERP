/**
 * API helpers for Correspondence Log.
 *
 * All endpoints are prefixed with /v1/correspondence/.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type CorrespondenceDirection = 'incoming' | 'outgoing';

export type CorrespondenceType = 'letter' | 'email' | 'notice' | 'memo';

export interface Correspondence {
  id: string;
  project_id: string;
  reference_number: string;
  subject: string;
  direction: CorrespondenceDirection;
  correspondence_type: CorrespondenceType;
  from_contact_id: string | null;
  to_contact_ids: string[];
  date_sent: string | null;
  date_received: string | null;
  notes: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface CorrespondenceFilters {
  project_id?: string;
  direction?: CorrespondenceDirection | '';
  type?: CorrespondenceType | '';
}

export interface CreateCorrespondencePayload {
  project_id: string;
  subject: string;
  direction: CorrespondenceDirection;
  correspondence_type: CorrespondenceType;
  from_contact_id?: string;
  to_contact_ids?: string[];
  date_sent?: string;
  date_received?: string;
  notes?: string;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchCorrespondence(
  filters?: CorrespondenceFilters,
): Promise<Correspondence[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.direction) params.set('direction', filters.direction);
  if (filters?.type) params.set('type', filters.type);
  const qs = params.toString();
  return apiGet<Correspondence[]>(`/v1/correspondence/${qs ? `?${qs}` : ''}`);
}

export async function createCorrespondence(
  data: CreateCorrespondencePayload,
): Promise<Correspondence> {
  return apiPost<Correspondence>('/v1/correspondence/', data);
}
