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
  | 'rejected'
  | 'closed';

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
  spec_section: string | null;
  type: SubmittalType;
  status: SubmittalStatus;
  ball_in_court: string | null;
  ball_in_court_name: string | null;
  revision: number;
  date_submitted: string | null;
  date_required: string | null;
  description: string | null;
  review_notes: string | null;
  /** BOQ position ids this submittal covers (deep-linked from the detail row). */
  linked_boq_item_ids: string[];
  /** Flexible blob; carries the source CDE container id when created from CDE. */
  metadata: Record<string, unknown>;
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
  description?: string;
  spec_section?: string;
  submittal_type: SubmittalType;
  date_required?: string;
  /** Optional blob persisted as-is; used to record the source CDE container. */
  metadata?: Record<string, unknown>;
}

export interface UpdateSubmittalPayload {
  title?: string;
  description?: string;
  spec_section?: string;
  submittal_type?: SubmittalType;
  date_required?: string;
}

export interface ReviewSubmittalPayload {
  status: 'approved' | 'approved_as_noted' | 'revise_and_resubmit' | 'rejected';
  notes?: string;
}

/**
 * The review-modal decision shape. ``approved`` is routed to the body-less
 * ``/approve/`` endpoint (final approval, MANAGER-gated, rate-limited);
 * every other decision is routed to ``/review/`` with the notes persisted.
 */
export interface ApproveSubmittalPayload {
  status: 'approved' | 'approved_as_noted' | 'revise_and_resubmit' | 'rejected';
  comments?: string;
}

/* ── Wire <-> UI normaliser ────────────────────────────────────────────── */

type SubmittalWire = Omit<
  Submittal,
  'type' | 'revision' | 'linked_boq_item_ids' | 'metadata'
> & {
  type?: SubmittalType;
  submittal_type?: SubmittalType;
  revision?: number;
  current_revision?: number;
  description?: string | null;
  review_notes?: string | null;
  ball_in_court_name?: string | null;
  linked_boq_item_ids?: string[] | null;
  metadata?: Record<string, unknown> | null;
};

function normaliseSubmittal(s: SubmittalWire): Submittal {
  const type = (s.type ?? s.submittal_type ?? 'shop_drawing') as SubmittalType;
  const revision = (s.revision ?? s.current_revision ?? 1) as number;
  return {
    ...s,
    type,
    revision,
    spec_section: s.spec_section ?? null,
    description: s.description ?? null,
    review_notes: s.review_notes ?? null,
    ball_in_court_name: s.ball_in_court_name ?? null,
    linked_boq_item_ids: s.linked_boq_item_ids ?? [],
    metadata: s.metadata ?? {},
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

/**
 * Final approval. The backend ``/approve/`` endpoint is MANAGER-gated and
 * rate-limited and unconditionally forces ``status='approved'``. It accepts
 * an optional body carrying the approver's ``notes`` so comments entered in
 * the approve modal are persisted (into metadata.review_notes) instead of
 * being silently dropped. Non-approve decisions (reject / revise /
 * approve-as-noted) must go through {@link reviewSubmittal}.
 */
export async function approveSubmittal(id: string, notes?: string): Promise<Submittal> {
  const row = await apiPost<SubmittalWire, { notes?: string }>(
    `/v1/submittals/${id}/approve/`,
    notes ? { notes } : {},
  );
  return normaliseSubmittal(row);
}

/**
 * Submit a review decision from the review modal. Routes ``approved`` to
 * the final-approval endpoint and every other decision to ``/review/`` so
 * Reject / Revise / Approve-as-Noted are persisted faithfully (and never
 * silently become ``approved``). Comments are forwarded as ``notes``.
 */
export async function submitReviewDecision(
  id: string,
  data: ApproveSubmittalPayload,
): Promise<Submittal> {
  if (data.status === 'approved') {
    return approveSubmittal(id, data.comments);
  }
  return reviewSubmittal(id, { status: data.status, notes: data.comments });
}
