// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Subcontractors module.
 *
 * Backed by /api/v1/subcontractors/ — see backend/app/modules/subcontractors/router.py
 */

import { apiGet, apiPost, apiPatch, apiDelete, isTruncated, type Page } from '@/shared/lib/api';

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
  // The GC's contract with the owner this subcontract sits under. Null means
  // "the project's only active client contract", resolved server-side.
  prime_contract_id?: string | null;
  // The same subcontract written in the contracts module, when there is one.
  // The agreement then carries the budget commitment and the contract does not.
  contract_id?: string | null;
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
  // Default GC schedule-of-values line this package's billing rolls up to.
  contract_line_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaymentApplicationLine {
  id: string;
  payment_application_id: string;
  work_package_id: string;
  // Per-line override of the work package's SOV line; null = use the package's.
  contract_line_id?: string | null;
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
  // What finance approved to pay, set at finance approval. The gross,
  // retention and net above stay as the sub claimed them. Null before the
  // approval, and on one approved before these existed, which was paid as
  // claimed.
  approved_gross_amount?: number | string | null;
  approved_retention_amount?: number | string | null;
  approved_net_amount?: number | string | null;
  paid_at?: string | null;
  rejection_reason?: string | null;
  // The GC progress claim this pay application was rolled into, if any.
  progress_claim_id?: string | null;
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
}): Promise<Page<Subcontractor>> {
  const qs = new URLSearchParams();
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  if (params?.prequalification_status) qs.set('prequalification_status', params.prequalification_status);
  if (params?.trade_category) qs.set('trade_category', params.trade_category);
  if (params?.active_only !== undefined) qs.set('active_only', String(params.active_only));
  const q = qs.toString();
  /* The `?` is unconditional. check_page_envelope_consumers.py binds a URL
     literal to the call it stands next to, and its URL pattern stops at the
     first whitespace, so the `${q ? `?${q}` : ''}` suffix this used to carry
     made the route invisible to it - the endpoint could go half migrated with
     the gate reporting nothing. A trailing `?` with an empty query is a valid
     URL and parses as no query at all. */
  return apiGet<Page<Subcontractor>>(`/v1/subcontractors/subcontractors/?${q}`);
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

export interface CreateAgreementPayload {
  subcontractor_id: string;
  project_id: string;
  title: string;
  total_value: string;
  currency: string;
  retention_percent: string;
  start_date?: string;
  end_date?: string;
  contract_id?: string;
}

/** Draw up an agreement. It is born a draft; activating it signs it. */
export function createAgreement(data: CreateAgreementPayload): Promise<Agreement> {
  return apiPost<Agreement>('/v1/subcontractors/agreements/', data);
}

export function updateAgreement(
  id: string,
  data: Partial<
    Pick<Agreement, 'title' | 'status' | 'notes' | 'requires_lien_waiver' | 'prime_contract_id'>
  >,
): Promise<Agreement> {
  return apiPatch<Agreement>(`/v1/subcontractors/agreements/${id}`, data);
}

export function listWorkPackages(agreementId: string): Promise<WorkPackage[]> {
  const qs = new URLSearchParams({ agreement_id: agreementId });
  return apiGet<WorkPackage[]>(`/v1/subcontractors/work-packages/?${qs.toString()}`);
}

export function updateWorkPackage(
  id: string,
  data: Partial<Pick<WorkPackage, 'name' | 'scope' | 'status' | 'contract_line_id'>>,
): Promise<WorkPackage> {
  return apiPatch<WorkPackage>(`/v1/subcontractors/work-packages/${id}`, data);
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

export interface SubmitPaymentApplicationPayload {
  agreement_id: string;
  gross_amount: string;
  period_start?: string;
  period_end?: string;
  currency?: string;
}

/** Submit a payment application; the server works out retention and net. */
export function submitPaymentApplication(data: SubmitPaymentApplicationPayload): Promise<PaymentApplication> {
  return apiPost<PaymentApplication>('/v1/subcontractors/payment-applications/', data);
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

// The pay application approval chain: submitted, then foreman approved, then
// finance approved, then paid, with reject open until it is paid. The backend
// gates each step by role, and the finance step and mark-paid by the release
// check above.

export function approvePaymentForeman(paymentId: string): Promise<PaymentApplication> {
  return apiPost<PaymentApplication>(
    `/v1/subcontractors/payment-applications/${paymentId}/approve-foreman`,
    {},
  );
}

/** One line's approved amount, as the person approving the payment confirmed it. */
export interface ApprovedLineAmount {
  line_id: string;
  approved_amount: string;
}

/**
 * Finance approval, with the amount approved on each line. Lines left out that
 * are still unset are approved as claimed; each named amount may be at most the
 * line's claim.
 */
export function approvePaymentFinance(
  paymentId: string,
  lines: ApprovedLineAmount[] = [],
): Promise<PaymentApplication> {
  return apiPost<PaymentApplication>(
    `/v1/subcontractors/payment-applications/${paymentId}/approve-finance`,
    { lines },
  );
}

export function markPaymentPaid(paymentId: string): Promise<PaymentApplication> {
  return apiPost<PaymentApplication>(
    `/v1/subcontractors/payment-applications/${paymentId}/mark-paid`,
    {},
  );
}

export function rejectPaymentApplication(paymentId: string, reason: string): Promise<PaymentApplication> {
  const qs = new URLSearchParams({ reason });
  return apiPost<PaymentApplication>(
    `/v1/subcontractors/payment-applications/${paymentId}/reject?${qs.toString()}`,
    {},
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

/* ── GC claim rollup ───────────────────────────────────────────────────── */
//
// Subcontractor pay applications rolled up into the GC's progress claim.
// Everything here reads, or records a person's choice (include, exclude,
// re-map a line); nothing writes the claim's own lines. Those still go
// through the contracts preview and its commit route.

export interface SubWaiverState {
  /** Strongest payment waiver on file: 'none' | 'conditional' | 'unconditional'. */
  state: string;
  amount_covered: number | string;
  covers_net: boolean;
  through_date: string | null;
  through_date_basis: 'through_date' | 'signed_date' | null;
}

export interface SubCertificateFinding {
  document_type: string;
  /** 'missing' | 'expired' | 'revoked' */
  state: string;
  source: string;
  lapsed_on: string | null;
}

export interface SubRollupPayApp {
  payment_application_id: string;
  application_number: string;
  agreement_id: string;
  agreement_title: string;
  subcontractor_id: string;
  subcontractor_name: string;
  status: PaymentApplicationStatus;
  period_start: string | null;
  period_end: string | null;
  currency: string;
  gross_amount: number | string;
  net_amount: number | string;
  claimed_amount: number | string;
  certified_amount: number | string;
  approved_amount: number | string;
  /** 0 means the pay application bills nothing on the claim, whatever its gross. */
  line_count: number;
  progress_claim_id: string | null;
  /** null when the claim has no period to compare against yet. */
  in_period: boolean | null;
  requires_lien_waiver: boolean;
  waiver: SubWaiverState;
  /** null when the claim has no period end to judge certificates on, or while a payment-date certificate waits for the payment. */
  certificates_ok: boolean | null;
  certificate_findings: SubCertificateFinding[];
  foreign_currency: boolean;
  /** Present only when the national pack reads a certificate on the payment date. */
  paid_on?: string | null;
  payment_date_findings?: SubPaymentDateFinding[] | null;
  certificates_pending_payment?: boolean | null;
}

export interface SubPaymentDateFinding {
  document_type: string;
  /** 'missing' | 'expired' | 'revoked' | 'undated' | 'pending' | 'pending_open' | 'pending_invalid' */
  state: string;
  judged_on: string | null;
  lapsed_on: string | null;
  valid_until: string | null;
}

export interface SubRollupRow {
  payment_application_id: string;
  application_number: string;
  agreement_id: string;
  subcontractor_id: string;
  subcontractor_name: string;
  status: PaymentApplicationStatus;
  claimed_amount: number | string;
  certified_amount: number | string;
  approved_amount: number | string;
  waiver_state: string;
  waiver_covers_net: boolean;
  certificates_ok: boolean | null;
  certificates_pending_payment?: boolean | null;
}

export interface SubRollupLine {
  contract_line_id: string;
  code: string;
  description: string;
  scheduled_value: number | string;
  gc_period_value: number | string;
  sub_period_approved: number | string;
  sub_approved_to_date: number | string;
  variance: number | string;
  exceeds_scheduled_value: boolean;
  subs: SubRollupRow[];
}

export interface SubRollupUnmappedLine {
  payment_application_id: string;
  application_number: string;
  line_id: string;
  work_package_id: string;
  work_package_name: string;
  approved_amount: number | string;
  claimed_amount: number | string;
  /** 'none' | 'foreign_line' | 'parent_line' */
  reason: string;
  contract_line_id: string | null;
}

export interface ClaimSubRollup {
  claim_id: string;
  contract_id: string;
  project_id: string;
  claim_status: string;
  currency: string;
  period_from: string | null;
  period_to: string | null;
  period_matching: 'dates' | 'parsed' | 'explicit_only';
  as_of: string | null;
  lines: SubRollupLine[];
  included: SubRollupPayApp[];
  candidates: SubRollupPayApp[];
  unmapped_lines: SubRollupUnmappedLine[];
  agreements: Array<{
    agreement_id: string;
    title: string;
    subcontractor_id: string;
    subcontractor_name: string;
    prime_contract_id: string | null;
    resolution: 'explicit' | 'single_active_client' | 'ambiguous' | 'none';
  }>;
  requirements: {
    certificate_types: string[];
    lien_waiver_required: boolean;
    source: string;
    reference: string | null;
  };
  skipped_foreign_currency: number;
  sub_period_approved_total: number | string;
  gc_period_total: number | string;
}

/** Same shape as the contracts progress preview, so one preview shows both. */
export interface SuggestedClaimLines {
  claim_id: string;
  contract_id: string;
  currency: string;
  items: Array<{
    contract_line_id: string;
    contract_line_code: string;
    contract_line_description: string;
    boq_position_id: string | null;
    unit: string | null;
    contract_quantity: number | string;
    contract_line_value: number | string;
    observed_pct: number | string;
    period_label: string | null;
    recorded_at: string | null;
    period_completed_qty: number | string;
    period_completed_value: number | string;
    cumulative_completed_value: number | string;
    origin: 'subcontract' | 'existing';
    current_period_value: number | string | null;
  }>;
  skipped_unlinked: number;
  skipped_no_progress: number;
  skipped_foreign_currency: number;
  gross: number | string;
  retention: number | string;
  prior_claims_total: number | string;
  net_due: number | string;
}

export function getClaimSubRollup(claimId: string): Promise<ClaimSubRollup> {
  return apiGet<ClaimSubRollup>(`/v1/subcontractors/progress-claims/${claimId}/rollup`);
}

export function includePayApplicationsInClaim(
  claimId: string,
  paymentApplicationIds: string[],
): Promise<PaymentApplication[]> {
  return apiPost<PaymentApplication[]>(
    `/v1/subcontractors/progress-claims/${claimId}/rollup/include`,
    { payment_application_ids: paymentApplicationIds },
  );
}

export function excludePayApplicationFromClaim(paymentId: string): Promise<PaymentApplication> {
  return apiPost<PaymentApplication>(
    `/v1/subcontractors/payment-applications/${paymentId}/exclude-from-claim`,
    {},
  );
}

export function getSuggestedClaimLines(claimId: string): Promise<SuggestedClaimLines> {
  return apiGet<SuggestedClaimLines>(
    `/v1/subcontractors/progress-claims/${claimId}/rollup/suggested-lines`,
  );
}

/** One page of a pay application's lines, as the route answers. */
export function getPaymentApplicationLinePage(
  paymentId: string,
  offset = 0,
  limit = 500,
): Promise<Page<PaymentApplicationLine>> {
  return apiGet<Page<PaymentApplicationLine>>(
    `/v1/subcontractors/payment-applications/${paymentId}/lines?offset=${offset}&limit=${limit}`,
  );
}

/**
 * Every line of a pay application, following the pages until none are left.
 *
 * The callers of this one approve an amount on each line and total what is
 * payable, so a first page would have them confirm part of a payment while
 * the screen read as the whole of it. Asking for the rest is cheap: a pay
 * application carries one line per work package, so the loop runs once in
 * practice and exists for the job that outgrows a page.
 */
export async function listPaymentApplicationLines(paymentId: string): Promise<PaymentApplicationLine[]> {
  const first = await getPaymentApplicationLinePage(paymentId);
  const rows = [...first.items];
  while (isTruncated({ items: rows, total: first.total })) {
    const next = await getPaymentApplicationLinePage(paymentId, rows.length);
    // A page that comes back empty cannot move us forward; stop rather than
    // ask for the same offset until the tab dies.
    if (next.items.length === 0) break;
    rows.push(...next.items);
  }
  return rows;
}

/** Re-map one pay-application line onto a GC SOV line; null clears the override. */
export function updatePaymentApplicationLine(
  lineId: string,
  data: { contract_line_id: string | null },
): Promise<PaymentApplicationLine> {
  return apiPatch<PaymentApplicationLine>(
    `/v1/subcontractors/payment-application-lines/${lineId}`,
    data,
  );
}
