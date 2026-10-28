// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Review Authority.
 *
 * All endpoints are prefixed with /v1/review-authority/. Mirrors the shape of
 * backend/app/modules/review_authority/{router,schemas,service}.py: a review
 * cycle is the FSM the project runs with an external approving authority
 * (state expertise, building control, an authority having jurisdiction, or a
 * technical review board); each cycle carries remarks that walk their own
 * open -> responded -> accepted|contested|withdrawn FSM.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Vocabularies (mirrors schemas.py) ────────────────────────────────── */

export const AUTHORITY_KINDS = [
  'state_expertise',
  'building_control',
  'ahj',
  'technical_review',
  'other',
] as const;
export type AuthorityKind = (typeof AUTHORITY_KINDS)[number];

export const CYCLE_STATUSES = [
  'draft',
  'submitted',
  'under_review',
  'remarks_issued',
  'responding',
  'resubmitted',
  'approved',
  'rejected',
  'withdrawn',
] as const;
export type CycleStatus = (typeof CYCLE_STATUSES)[number];

/** Mirrors CYCLE_TRANSITIONS in service.py — the single source of truth for
 * which target statuses are legal from a given cycle status. Kept here so the
 * UI only ever offers a legal move; the backend still re-validates. */
export const CYCLE_TRANSITIONS: Record<CycleStatus, readonly CycleStatus[]> = {
  draft: ['submitted', 'withdrawn'],
  submitted: ['under_review', 'withdrawn'],
  under_review: ['remarks_issued', 'approved', 'rejected', 'withdrawn'],
  remarks_issued: ['responding', 'withdrawn'],
  responding: ['resubmitted', 'withdrawn'],
  resubmitted: ['under_review', 'approved', 'rejected', 'withdrawn'],
  approved: [],
  rejected: [],
  withdrawn: [],
};
export const CYCLE_TERMINAL_STATUSES: readonly CycleStatus[] = ['approved', 'rejected', 'withdrawn'];

export const REMARK_STATUSES = ['open', 'responded', 'accepted', 'contested', 'withdrawn'] as const;
export type RemarkStatus = (typeof REMARK_STATUSES)[number];

export const REMARK_CLASSIFICATIONS = [
  'has_norm_ref',
  'no_norm_ref_contestable',
  'clarification',
  'defect',
] as const;
export type RemarkClassification = (typeof REMARK_CLASSIFICATIONS)[number];

export const REMARK_SEVERITIES = ['blocking', 'major', 'minor', 'info'] as const;
export type RemarkSeverity = (typeof REMARK_SEVERITIES)[number];

export const REMARK_DECISIONS = ['accepted', 'contested', 'withdrawn'] as const;
export type RemarkDecision = (typeof REMARK_DECISIONS)[number];

/* ── Types ─────────────────────────────────────────────────────────────── */

export interface ReviewCycle {
  id: string;
  project_id: string;
  authority_name: string;
  authority_kind: AuthorityKind;
  submission_ref: string | null;
  pinned_document_version: string | null;
  current_document_version: string;
  status: CycleStatus;
  opened_at: string | null;
  due_at: string | null;
  sla_days: number;
  jurisdiction: string | null;
  notes: string;
  metadata: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  /** Computed: negative once overdue, null until submitted. */
  days_remaining: number | null;
  /** Computed: true when past the SLA due date and not yet decided. */
  overdue: boolean;
}

export interface Remark {
  id: string;
  cycle_id: string;
  project_id: string;
  ordinal: number;
  section: string | null;
  text: string;
  norm_reference: string | null;
  classification: RemarkClassification;
  severity: RemarkSeverity;
  status: RemarkStatus;
  response_text: string | null;
  responded_at: string | null;
  repeat_of_id: string | null;
  metadata: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  /** Computed: true when the cycle's live document has moved past the version this remark was raised against. */
  is_stale: boolean;
}

export interface RepeatRadarRow {
  remark_id: string;
  ordinal: number;
  text: string;
  repeat_of_id: string;
  repeat_of_ordinal: number | null;
  similarity: number | null;
}

export interface ReviewAuthorityMeta {
  authority_kinds: { code: string; label: string }[];
  cycle_statuses: { code: string; label: string }[];
  remark_statuses: string[];
  remark_classifications: { code: string; label: string }[];
  remark_severities: string[];
  remark_decisions: string[];
}

export interface CreateCyclePayload {
  project_id: string;
  authority_name: string;
  authority_kind?: AuthorityKind;
  submission_ref?: string;
  current_document_version?: string;
  sla_days?: number;
  due_at?: string;
  jurisdiction?: string;
  notes?: string;
  metadata?: Record<string, unknown>;
}

export interface UpdateCyclePayload {
  authority_name?: string;
  authority_kind?: AuthorityKind;
  submission_ref?: string;
  current_document_version?: string;
  sla_days?: number;
  due_at?: string | null;
  jurisdiction?: string;
  notes?: string;
  metadata?: Record<string, unknown>;
}

export interface SubmitCyclePayload {
  document_version?: string;
  submission_ref?: string;
}

export interface CreateRemarkPayload {
  text: string;
  section?: string;
  norm_reference?: string;
  classification?: RemarkClassification;
  severity?: RemarkSeverity;
  metadata?: Record<string, unknown>;
}

/* ── Cycles ────────────────────────────────────────────────────────────── */

export async function fetchCycles(params: {
  project_id: string;
  status?: CycleStatus | '';
  authority_kind?: AuthorityKind | '';
}): Promise<ReviewCycle[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.authority_kind) qs.set('authority_kind', params.authority_kind);
  return apiGet<ReviewCycle[]>(`/v1/review-authority/cycles/?${qs.toString()}`);
}

export async function fetchCycle(cycleId: string): Promise<ReviewCycle> {
  return apiGet<ReviewCycle>(`/v1/review-authority/cycles/${cycleId}/`);
}

export async function createCycle(data: CreateCyclePayload): Promise<ReviewCycle> {
  return apiPost<ReviewCycle>('/v1/review-authority/cycles/', data);
}

export async function updateCycle(cycleId: string, data: UpdateCyclePayload): Promise<ReviewCycle> {
  return apiPatch<ReviewCycle>(`/v1/review-authority/cycles/${cycleId}/`, data);
}

export async function deleteCycle(cycleId: string): Promise<void> {
  await apiDelete(`/v1/review-authority/cycles/${cycleId}/`);
}

export async function submitCycle(cycleId: string, data: SubmitCyclePayload): Promise<ReviewCycle> {
  return apiPost<ReviewCycle>(`/v1/review-authority/cycles/${cycleId}/submit`, data);
}

export async function transitionCycle(cycleId: string, targetStatus: CycleStatus): Promise<ReviewCycle> {
  return apiPost<ReviewCycle>(`/v1/review-authority/cycles/${cycleId}/transition`, {
    target_status: targetStatus,
  });
}

/* ── Remarks ───────────────────────────────────────────────────────────── */

export async function fetchRemarks(cycleId: string): Promise<Remark[]> {
  return apiGet<Remark[]>(`/v1/review-authority/cycles/${cycleId}/remarks/`);
}

export async function addRemark(cycleId: string, data: CreateRemarkPayload): Promise<Remark> {
  return apiPost<Remark>(`/v1/review-authority/cycles/${cycleId}/remarks`, data);
}

export async function respondRemark(remarkId: string, responseText: string): Promise<Remark> {
  return apiPost<Remark>(`/v1/review-authority/remarks/${remarkId}/respond`, {
    response_text: responseText,
  });
}

export async function decideRemark(
  remarkId: string,
  decision: RemarkDecision,
  note?: string,
): Promise<Remark> {
  return apiPost<Remark>(`/v1/review-authority/remarks/${remarkId}/decide`, { decision, note });
}

/* ── Derived views ─────────────────────────────────────────────────────── */

export async function fetchStaleRemarks(cycleId: string): Promise<Remark[]> {
  return apiGet<Remark[]>(`/v1/review-authority/cycles/${cycleId}/stale-remarks`);
}

export async function fetchRepeatRadar(cycleId: string): Promise<RepeatRadarRow[]> {
  return apiGet<RepeatRadarRow[]>(`/v1/review-authority/cycles/${cycleId}/repeat-radar`);
}

export async function fetchDossier(cycleId: string): Promise<Record<string, unknown>> {
  return apiGet<Record<string, unknown>>(`/v1/review-authority/cycles/${cycleId}/dossier`);
}

export async function fetchMeta(): Promise<ReviewAuthorityMeta> {
  return apiGet<ReviewAuthorityMeta>('/v1/review-authority/meta');
}
