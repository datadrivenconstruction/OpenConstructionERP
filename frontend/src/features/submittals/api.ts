/**
 * API helpers for Submittals.
 *
 * All endpoints are prefixed with /v1/submittals/.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

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

export interface ReviewSubmittalPayload {
  comments: string;
}

export interface ApproveSubmittalPayload {
  status: 'approved' | 'approved_as_noted' | 'revise_and_resubmit' | 'rejected';
  comments?: string;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchSubmittals(filters?: SubmittalFilters): Promise<Submittal[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  const qs = params.toString();
  return apiGet<Submittal[]>(`/v1/submittals/${qs ? `?${qs}` : ''}`);
}

export async function createSubmittal(data: CreateSubmittalPayload): Promise<Submittal> {
  return apiPost<Submittal>('/v1/submittals/', data);
}

export async function submitSubmittal(id: string): Promise<Submittal> {
  return apiPost<Submittal>(`/v1/submittals/${id}/submit/`);
}

export async function reviewSubmittal(id: string, data: ReviewSubmittalPayload): Promise<Submittal> {
  return apiPost<Submittal>(`/v1/submittals/${id}/review/`, data);
}

export async function approveSubmittal(id: string, data: ApproveSubmittalPayload): Promise<Submittal> {
  return apiPost<Submittal>(`/v1/submittals/${id}/approve/`, data);
}
