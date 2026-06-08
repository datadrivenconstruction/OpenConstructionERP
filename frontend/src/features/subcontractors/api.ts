/**
 * API helpers for the Subcontractors module.
 *
 * Backed by /api/v1/subcontractors/ — see backend/app/modules/subcontractors/router.py
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type PrequalStatus = 'pending' | 'approved' | 'suspended' | 'rejected';
export type AgreementStatus = 'draft' | 'active' | 'completed' | 'terminated';
export type WorkPackageStatus = 'planned' | 'in_progress' | 'completed';
export type PaymentApplicationStatus =
  | 'submitted'
  | 'foreman_approved'
  | 'finance_approved'
  | 'paid'
  | 'rejected';
export type CertType = 'insurance' | 'license' | 'iso' | 'safety' | 'bond';
export type PrequalApplicationStatus =
  | 'draft'
  | 'submitted'
  | 'under_review'
  | 'approved'
  | 'rejected';

export interface Subcontractor {
  id: string;
  contact_id?: string | null;
  legal_name: string;
  trade_name?: string | null;
  tax_id?: string | null;
  trade_categories: string[];
  prequalification_status: PrequalStatus;
  rating_score: number | string;
  country?: string | null;
  address?: Record<string, unknown> | null;
  website?: string | null;
  notes?: string | null;
  is_active: boolean;
  // ── Wave 4 / T12: subcontractor-prequalification-platform-style prequal + insurance tracking ──
  prequal_score?: number | null;
  insurance_expiry_date?: string | null; // ISO date (yyyy-mm-dd)
  insurance_doc_id?: string | null;
  prequal_questionnaire?: Record<string, unknown> | null;
  prequal_completed_at?: string | null;
  blocked_reason?: string | null;
  is_blocked?: boolean;
  created_by?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface InsuranceExpiryEntry {
  id: string;
  legal_name: string;
  insurance_expiry_date?: string | null;
  days_until_expiry: number;
  is_blocked: boolean;
}

export interface SubcontractorContact {
  id: string;
  subcontractor_id: string;
  name: string;
  role?: string | null;
  email?: string | null;
  phone?: string | null;
  primary: boolean;
  created_at: string;
  updated_at: string;
}

export interface Prequalification {
  id: string;
  subcontractor_id: string;
  submitted_at?: string | null;
  status: PrequalApplicationStatus;
  answers: Record<string, unknown>;
  reviewer_id?: string | null;
  decision_at?: string | null;
  decision_notes?: string | null;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Certificate {
  id: string;
  subcontractor_id: string;
  cert_type: CertType;
  issued_by?: string | null;
  issue_date?: string | null;
  valid_until?: string | null;
  document_url?: string | null;
  status: string;
  revoked: boolean;
  notes?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Agreement {
  id: string;
  subcontractor_id: string;
  project_id: string;
  title: string;
  total_value: number | string;
  currency: string;
  start_date?: string | null;
  end_date?: string | null;
  retention_percent: number | string;
  retention_release_event?: string | null;
  status: AgreementStatus;
  // When true, every payment application under this agreement is held until a
  // signed lien waiver covering the net amount is on file (TOP-30 #9).
  requires_lien_waiver: boolean;
  notes?: string | null;
  created_by?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface WorkPackage {
  id: string;
  agreement_id: string;
  name: string;
  scope?: string | null;
  planned_value: number | string;
  completion_percent: number | string;
  status: WorkPackageStatus;
  created_at: string;
  updated_at: string;
}

export interface PaymentApplicationLine {
  id: string;
  payment_application_id: string;
  work_package_id: string;
  claimed_amount: number | string;
  certified_amount: number | string;
  approved_amount: number | string;
}

export interface PaymentApplication {
  id: string;
  agreement_id: string;
  application_number: string;
  period_start?: string | null;
  period_end?: string | null;
  gross_amount: number | string;
  retention_amount: number | string;
  net_amount: number | string;
  currency: string;
  status: PaymentApplicationStatus;
  submitted_at?: string | null;
  foreman_approved_at?: string | null;
  foreman_approved_by?: string | null;
  finance_approved_at?: string | null;
  finance_approved_by?: string | null;
  paid_at?: string | null;
  rejection_reason?: string | null;
  created_by?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface RetentionLedgerEntry {
  id: string;
  agreement_id: string;
  payment_application_id?: string | null;
  accrued_amount: number | string;
  released_amount: number | string;
  released_at?: string | null;
  release_reason?: string | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Rating {
  id: string;
  subcontractor_id: string;
  period: string;
  quality_score: number | string;
  hse_score: number | string;
  schedule_score: number | string;
  cost_score: number | string;
  overall_score: number | string;
  basis: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SubcontractorDashboard {
  subcontractor_id: string;
  legal_name: string;
  prequalification_status: PrequalStatus;
  rating_score: number | string;
  active_agreements: number;
  open_payment_applications: number;
  pending_retention: number | string;
  expired_certificates: number;
  expiring_soon_certificates: number;
  blocked: boolean;
  block_reasons: string[];
}

export interface CreateSubcontractorPayload {
  legal_name: string;
  trade_name?: string;
  tax_id?: string;
  trade_categories?: string[];
  country?: string;
  website?: string;
  notes?: string;
  prequalification_status?: PrequalStatus;
}

/* ── Subcontractors ────────────────────────────────────────────────────── */

export function listSubcontractors(params?: {
  offset?: number;
  limit?: number;
  prequalification_status?: string;
  trade_category?: string;
  active_only?: boolean;
}): Promise<Subcontractor[]> {
  const qs = new URLSearchParams();
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  if (params?.prequalification_status) qs.set('prequalification_status', params.prequalification_status);
  if (params?.trade_category) qs.set('trade_category', params.trade_category);
  if (params?.active_only !== undefined) qs.set('active_only', String(params.active_only));
  const q = qs.toString();
  return apiGet<Subcontractor[]>(`/v1/subcontractors/subcontractors/${q ? `?${q}` : ''}`);
}

export function getSubcontractor(id: string): Promise<Subcontractor> {
  return apiGet<Subcontractor>(`/v1/subcontractors/subcontractors/${id}`);
}

export function createSubcontractor(data: CreateSubcontractorPayload): Promise<Subcontractor> {
  return apiPost<Subcontractor>('/v1/subcontractors/subcontractors/', data);
}

export function updateSubcontractor(
  id: string,
  data: Partial<CreateSubcontractorPayload>,
): Promise<Subcontractor> {
  return apiPatch<Subcontractor>(`/v1/subcontractors/subcontractors/${id}`, data);
}

export function deleteSubcontractor(id: string): Promise<void> {
  return apiDelete(`/v1/subcontractors/subcontractors/${id}`);
}

export function getSubcontractorDashboard(id: string): Promise<SubcontractorDashboard> {
  return apiGet<SubcontractorDashboard>(`/v1/subcontractors/subcontractors/${id}/dashboard`);
}

/* ── Agreements / Scope ────────────────────────────────────────────────── */

export function listAgreements(params: {
  subcontractor_id?: string;
  project_id?: string;
  status?: string;
}): Promise<Agreement[]> {
  const qs = new URLSearchParams();
  if (params.subcontractor_id) qs.set('subcontractor_id', params.subcontractor_id);
  if (params.project_id) qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  return apiGet<Agreement[]>(`/v1/subcontractors/agreements/?${qs.toString()}`);
}

export function updateAgreement(
  id: string,
  data: Partial<Pick<Agreement, 'title' | 'status' | 'notes' | 'requires_lien_waiver'>>,
): Promise<Agreement> {
  return apiPatch<Agreement>(`/v1/subcontractors/agreements/${id}`, data);
}

export function listWorkPackages(agreementId: string): Promise<WorkPackage[]> {
  const qs = new URLSearchParams({ agreement_id: agreementId });
  return apiGet<WorkPackage[]>(`/v1/subcontractors/work-packages/?${qs.toString()}`);
}

/* ── Payments / Retention ──────────────────────────────────────────────── */

export function listPaymentApplications(params: {
  agreement_id: string;
  status?: string;
}): Promise<PaymentApplication[]> {
  const qs = new URLSearchParams({ agreement_id: params.agreement_id });
  if (params.status) qs.set('status', params.status);
  return apiGet<PaymentApplication[]>(`/v1/subcontractors/payment-applications/?${qs.toString()}`);
}

export function listRetentionLedger(agreementId: string): Promise<RetentionLedgerEntry[]> {
  const qs = new URLSearchParams({ agreement_id: agreementId });
  return apiGet<RetentionLedgerEntry[]>(`/v1/subcontractors/retention/ledger?${qs.toString()}`);
}

/**
 * Lien-waiver release gate for a single payment application (TOP-30 #9).
 *
 * `waiver_required` mirrors the agreement flag; `blocked` is true when the
 * gate would refuse finance approval / mark-paid right now, with `reasons`
 * one of `missing_waiver` / `waiver_amount_mismatch`.
 */
export interface PaymentReleaseCheck {
  payment_application_id: string;
  waiver_required: boolean;
  blocked: boolean;
  reasons: string[];
}

export function getPaymentReleaseCheck(paymentId: string): Promise<PaymentReleaseCheck> {
  return apiGet<PaymentReleaseCheck>(
    `/v1/subcontractors/payment-applications/${paymentId}/release-check`,
  );
}

/* ── Certificates ──────────────────────────────────────────────────────── */

export function listCertificates(subcontractorId: string): Promise<Certificate[]> {
  const qs = new URLSearchParams({ subcontractor_id: subcontractorId });
  return apiGet<Certificate[]>(`/v1/subcontractors/certificates/?${qs.toString()}`);
}

/* ── Ratings ───────────────────────────────────────────────────────────── */

export function listRatings(subcontractorId: string): Promise<Rating[]> {
  const qs = new URLSearchParams({ subcontractor_id: subcontractorId });
  return apiGet<Rating[]>(`/v1/subcontractors/ratings/?${qs.toString()}`);
}

/**
 * Recompute the monthly rating rollup for a subcontractor (TOP-30 #20).
 *
 * `period` is a YYYY-MM string. MANAGER-only on the backend. The compute is
 * idempotent — re-running for the same month refreshes the figures rather than
 * creating a duplicate row — and emits `subcontractors.rating.updated`.
 */
export function computeMonthlyRating(
  subId: string,
  period: string,
): Promise<Rating> {
  const qs = new URLSearchParams({ period });
  return apiPost<Rating>(
    `/v1/subcontractors/subcontractors/${subId}/ratings/compute?${qs.toString()}`,
    {},
  );
}

/* ── Award eligibility + prequalification (TOP-30 #20) ──────────────────── */

export interface AwardEligibility {
  subcontractor_id: string;
  awardable: boolean;
  reasons: string[];
}

export function getAwardEligibility(subId: string): Promise<AwardEligibility> {
  return apiGet<AwardEligibility>(
    `/v1/subcontractors/subcontractors/${subId}/award-eligibility`,
  );
}

export interface PrequalView {
  subcontractor_id: string;
  prequalification_status: PrequalStatus;
  prequal_score?: number | null;
  prequal_questionnaire?: Record<string, unknown> | null;
  prequal_completed_at?: string | null;
  is_blocked: boolean;
  blocked_reason?: string | null;
  missing_required: string[];
  computed_score?: number | null;
  approval_threshold: number;
}

export function getPrequalView(subId: string): Promise<PrequalView> {
  return apiGet<PrequalView>(
    `/v1/subcontractors/subcontractors/${subId}/prequal`,
  );
}

/* ── Wave 4 / T12: Prequal + block + insurance ─────────────────────────── */

export interface PrequalRequestPayload {
  questionnaire: Record<string, unknown>;
  score?: number | null;
}

export function submitPrequal(
  subId: string,
  payload: PrequalRequestPayload,
): Promise<Subcontractor> {
  return apiPost<Subcontractor>(
    `/v1/subcontractors/subcontractors/${subId}/prequal`,
    payload,
  );
}

export function checkInsuranceExpiry(
  daysAhead: number = 30,
): Promise<InsuranceExpiryEntry[]> {
  const qs = new URLSearchParams({ days_ahead: String(daysAhead) });
  return apiPost<InsuranceExpiryEntry[]>(
    `/v1/subcontractors/subcontractors/check-insurance-expiry?${qs.toString()}`,
    {},
  );
}

export function blockSubcontractor(
  subId: string,
  reason: string,
): Promise<Subcontractor> {
  return apiPost<Subcontractor>(
    `/v1/subcontractors/subcontractors/${subId}/block`,
    { reason },
  );
}

export function unblockSubcontractor(subId: string): Promise<Subcontractor> {
  return apiPost<Subcontractor>(
    `/v1/subcontractors/subcontractors/${subId}/unblock`,
    {},
  );
}
