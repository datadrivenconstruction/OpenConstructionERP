/**
 * API helpers for Submittals.
 *
 * All endpoints are prefixed with /v1/submittals/.
 */

import { apiGet, apiPost, apiPatch } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type SubmittalStatus =
  | 'draft'
  | 'submitted'
  | 'under_review'
  | 'approved'
  | 'approved_as_noted'
  | 'revise_and_resubmit'
  | 'rejected';

export type SubmittalType =
  | 'shop_drawing'
  | 'product_data'
  | 'sample'
  | 'mock_up'
  | 'test_report'
  | 'certificate'
  | 'warranty';

export interface Submittal {
  id: string;
  project_id: string;
  submittal_number: string;
  title: string;
  spec_section: string;
  type: SubmittalType;
  status: SubmittalStatus;
  ball_in_court: string | null;
  ball_in_court_name: string | null;
  revision: number;
  date_submitted: string | null;
  date_required: string | null;
  description: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SubmittalFilters {
  project_id?: string;
  status?: SubmittalStatus | '';
}

export interface CreateSubmittalPayload {
  project_id: string;
  title: string;
  spec_section?: string;
  submittal_type: SubmittalType;
  date_required?: string;
}

export interface UpdateSubmittalPayload {
  title?: string;
  spec_section?: string;
  submittal_type?: SubmittalType;
  date_required?: string;
}

export interface ReviewSubmittalPayload {
  comments: string;
}

export interface ApproveSubmittalPayload {
  status: 'approved' | 'approved_as_noted' | 'revise_and_resubmit' | 'rejected';
  comments?: string;
}

/* ── Wire <-> UI normaliser ────────────────────────────────────────────── */

type SubmittalWire = Omit<Submittal, 'type' | 'revision'> & {
  type?: SubmittalType;
  submittal_type?: SubmittalType;
  revision?: number;
  current_revision?: number;
  description?: string | null;
  ball_in_court_name?: string | null;
};

function normaliseSubmittal(s: SubmittalWire): Submittal {
  const type = (s.type ?? s.submittal_type ?? 'shop_drawing') as SubmittalType;
  const revision = (s.revision ?? s.current_revision ?? 1) as number;
  return {
    ...s,
    type,
    revision,
    description: s.description ?? null,
    ball_in_court_name: s.ball_in_court_name ?? null,
  } as Submittal;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchSubmittals(filters?: SubmittalFilters): Promise<Submittal[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  const qs = params.toString();
  const rows = await apiGet<SubmittalWire[]>(`/v1/submittals/${qs ? `?${qs}` : ''}`);
  return rows.map(normaliseSubmittal);
}

export async function createSubmittal(data: CreateSubmittalPayload): Promise<Submittal> {
  const row = await apiPost<SubmittalWire>('/v1/submittals/', data);
  return normaliseSubmittal(row);
}

export async function updateSubmittal(id: string, data: UpdateSubmittalPayload): Promise<Submittal> {
  const row = await apiPatch<SubmittalWire, UpdateSubmittalPayload>(`/v1/submittals/${id}`, data);
  return normaliseSubmittal(row);
}

export async function submitSubmittal(id: string): Promise<Submittal> {
  const row = await apiPost<SubmittalWire>(`/v1/submittals/${id}/submit/`);
  return normaliseSubmittal(row);
}

export async function reviewSubmittal(id: string, data: ReviewSubmittalPayload): Promise<Submittal> {
  const row = await apiPost<SubmittalWire>(`/v1/submittals/${id}/review/`, data);
  return normaliseSubmittal(row);
}

export async function approveSubmittal(id: string, data: ApproveSubmittalPayload): Promise<Submittal> {
  const row = await apiPost<SubmittalWire>(`/v1/submittals/${id}/approve/`, data);
  return normaliseSubmittal(row);
}
