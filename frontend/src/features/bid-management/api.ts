// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Bid Management module.
 *
 * Backed by /api/v1/bid-management/ — see
 * backend/app/modules/bid_management/router.py
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type BidPackageStatus =
  | 'draft'
  | 'published'
  | 'open'
  | 'closed'
  | 'cancelled'
  | 'awarded';

export type BidConfidentiality = 'public' | 'limited' | 'confidential';

export type BidInvitationStatus =
  | 'pending'
  | 'sent'
  | 'opened'
  | 'submitted'
  | 'declined'
  | 'expired';

export type BidderStatus = 'active' | 'disqualified' | 'withdrawn';

export type BidRejectionCode =
  | 'price'
  | 'scope'
  | 'completeness'
  | 'qualification'
  | 'other';

export interface BidPackage {
  id: string;
  project_id: string;
  tender_id: string | null;
  code: string;
  title: string;
  scope_description: string;
  instructions_to_bidders: string;
  submission_deadline: string | null;
  decision_due_by: string | null;
  currency: string;
  total_budget_estimate: number | string;
  status: BidPackageStatus;
  confidentiality_level: BidConfidentiality;
  published_at: string | null;
  closed_at: string | null;
  awarded_at: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface BidPackageLineItem {
  id: string;
  package_id: string;
  code: string;
  description: string;
  unit: string;
  quantity: number | string;
  alternative_allowed: boolean;
  order_index: number;
  parent_line_id: string | null;
  spec_attachment_url: string | null;
  is_mandatory: boolean;
  /** Bill position the line was added from; carried onto the contract line on award. */
  boq_position_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface BidInvitation {
  id: string;
  package_id: string;
  bidder_ref_id: string | null;
  invitee_email: string;
  invitee_company_name: string;
  sent_at: string | null;
  opened_at: string | null;
  submission_received_at: string | null;
  declined_at: string | null;
  decline_reason: string | null;
  status: BidInvitationStatus;
  token_hash: string | null;
  created_at: string;
  updated_at: string;
}

export interface Bidder {
  id: string;
  package_id: string;
  company_name: string;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  country: string;
  status: BidderStatus;
  disqualification_reason: string | null;
  notes: string;
  /** Directory entry the bidder was invited from; the award's contract counterparty. */
  subcontractor_id: string | null;
  contact_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface BidSubmission {
  id: string;
  invitation_id: string;
  bidder_id: string;
  submitted_at: string | null;
  total_amount: number | string;
  currency: string;
  completeness_score: number | string;
  notes_to_owner: string;
  exclusions: string[];
  qualifications: string[];
  is_valid: boolean;
  open_after_deadline: boolean;
  envelope_payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface BidSubmissionLine {
  id: string;
  submission_id: string;
  line_item_id: string;
  unit_price: number | string;
  quantity_priced: number | string;
  total_price: number | string;
  alternative_offered: boolean;
  alternative_description: string;
  comment: string;
  created_at: string;
  updated_at: string;
}

export interface BidQA {
  id: string;
  package_id: string;
  bidder_id: string | null;
  question: string;
  asked_at: string | null;
  asked_by_email: string;
  answer: string;
  answered_at: string | null;
  answered_by: string | null;
  is_public: boolean;
  visible_to_bidder_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface BidComparison {
  id: string;
  package_id: string;
  computed_at: string | null;
  normalized_low: number | string;
  normalized_high: number | string;
  technical_scoring_rule: Record<string, unknown>;
  commercial_weight_pct: number;
  technical_weight_pct: number;
  recommended_bidder_id: string | null;
  recommended_reason: string;
  created_at: string;
  updated_at: string;
}

export interface BidLevelingRow {
  id: string;
  comparison_id: string;
  bidder_id: string;
  raw_total: number | string;
  normalized_total: number | string;
  commercial_score: number | string;
  technical_score: number | string;
  total_score: number | string;
  rank: number;
  manual_adjustment: number | string;
  manual_adjustment_reason: string;
  created_at: string;
  updated_at: string;
}

export interface LevelingTable {
  comparison_id: string;
  package_id: string;
  computed_at: string | null;
  rows: BidLevelingRow[];
  recommended_bidder_id: string | null;
  recommended_reason: string;
}

export interface LevelingMatrixCell {
  bidder_id: string;
  company_name: string;
  unit_price: number | string;
  quantity_priced: number | string;
  total_price: number | string;
  inclusion_status: string;
  alternative_offered: boolean;
  comment: string;
  prevailing_wage_applicable: boolean;
  is_low: boolean;
}

export interface LevelingMatrixRow {
  line_item_id: string;
  line_item_code: string;
  description: string;
  unit: string;
  quantity: number | string;
  is_mandatory: boolean;
  cells: LevelingMatrixCell[];
  excluded_count: number;
  clarification_count: number;
}

export interface LevelingMatrix {
  package_id: string;
  bidder_ids: string[];
  bidder_names: string[];
  rows: LevelingMatrixRow[];
}

export interface BidAward {
  id: string;
  package_id: string;
  awarded_bidder_id: string;
  awarded_amount: number | string;
  currency: string;
  decision_summary: string;
  decision_signed_by: string | null;
  decision_signed_at: string | null;
  contract_template_ref: string;
  notified_others_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PackageDashboard {
  package_id: string;
  code: string;
  title: string;
  status: BidPackageStatus;
  invitations_count: number;
  submissions_count: number;
  declined_count: number;
  open_questions_count: number;
  answered_questions_count: number;
  leveling_computed: boolean;
  awarded_bidder_id: string | null;
}

/* ── Create payloads ────────────────────────────────────────────────────── */

export interface CreatePackagePayload {
  project_id: string;
  tender_id?: string | null;
  code: string;
  title?: string;
  scope_description?: string;
  instructions_to_bidders?: string;
  submission_deadline?: string | null;
  decision_due_by?: string | null;
  currency?: string;
  total_budget_estimate?: number | string;
  status?: BidPackageStatus;
  confidentiality_level?: BidConfidentiality;
}

export interface CreateBidderPayload {
  package_id: string;
  company_name: string;
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  country?: string;
  notes?: string;
  subcontractor_id?: string | null;
  contact_id?: string | null;
}

export interface CreateInvitationPayload {
  package_id: string;
  bidder_ref_id?: string | null;
  invitee_email: string;
  invitee_company_name?: string;
}

export interface CreateQAPayload {
  package_id: string;
  bidder_id?: string | null;
  question: string;
  asked_by_email?: string;
  is_public?: boolean;
}

export interface AnswerQAPayload {
  answer: string;
  is_public?: boolean;
}

export interface CreateComparisonPayload {
  package_id: string;
  commercial_weight_pct?: number;
  technical_weight_pct?: number;
}

export interface CreateAwardPayload {
  package_id: string;
  awarded_bidder_id: string;
  awarded_amount: number | string;
  currency?: string;
  decision_summary?: string;
  contract_template_ref?: string;
}

/* ── Packages ──────────────────────────────────────────────────────────── */

export function listPackages(params: {
  project_id: string;
  status?: string;
  offset?: number;
  limit?: number;
}): Promise<BidPackage[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.offset !== undefined) qs.set('offset', String(params.offset));
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<BidPackage[]>(`/v1/bid-management/bid-packages/?${qs.toString()}`);
}

export function getPackage(id: string): Promise<BidPackage> {
  return apiGet<BidPackage>(`/v1/bid-management/bid-packages/${id}`);
}

/* ── Scope line items ──────────────────────────────────────────────────── */

export interface CreateLineItemPayload {
  package_id: string;
  code?: string;
  description?: string;
  unit?: string;
  quantity?: number | string;
  is_mandatory?: boolean;
  order_index?: number;
}

export function listLineItems(packageId: string): Promise<BidPackageLineItem[]> {
  return apiGet<BidPackageLineItem[]>(
    `/v1/bid-management/bid-package-line-items/?package_id=${packageId}`,
  );
}

export function createLineItem(data: CreateLineItemPayload): Promise<BidPackageLineItem> {
  return apiPost<BidPackageLineItem>('/v1/bid-management/bid-package-line-items/', data);
}

/**
 * Copy bill positions into the package as scope lines, keeping the link to
 * each. Returns only the lines created: positions already in the package and
 * section headers are skipped by the server.
 */
export function addLinesFromBoq(
  packageId: string,
  positionIds: string[],
): Promise<BidPackageLineItem[]> {
  return apiPost<BidPackageLineItem[]>(
    `/v1/bid-management/bid-packages/${packageId}/lines/from-boq`,
    { position_ids: positionIds },
  );
}

export function deleteLineItem(id: string): Promise<void> {
  return apiDelete(`/v1/bid-management/bid-package-line-items/${id}`);
}

export function createPackage(data: CreatePackagePayload): Promise<BidPackage> {
  return apiPost<BidPackage>('/v1/bid-management/bid-packages/', data);
}

export function updatePackage(
  id: string,
  data: Partial<CreatePackagePayload>,
): Promise<BidPackage> {
  return apiPatch<BidPackage>(`/v1/bid-management/bid-packages/${id}`, data);
}

export function deletePackage(id: string): Promise<void> {
  return apiDelete(`/v1/bid-management/bid-packages/${id}`);
}

export function publishPackage(id: string): Promise<BidPackage> {
  return apiPost<BidPackage>(`/v1/bid-management/bid-packages/${id}/publish`, {});
}

export function openBids(id: string): Promise<BidPackage> {
  return apiPost<BidPackage>(`/v1/bid-management/bid-packages/${id}/open-bids`, {});
}

export function closePackage(id: string): Promise<BidPackage> {
  return apiPost<BidPackage>(`/v1/bid-management/bid-packages/${id}/close`, {});
}

export function cancelPackage(id: string, reason = ''): Promise<BidPackage> {
  const qs = reason ? `?reason=${encodeURIComponent(reason)}` : '';
  return apiPost<BidPackage>(`/v1/bid-management/bid-packages/${id}/cancel${qs}`, {});
}

export function awardPackage(
  id: string,
  data: CreateAwardPayload,
): Promise<BidAward> {
  return apiPost<BidAward>(`/v1/bid-management/bid-packages/${id}/award`, data);
}

export function packageDashboard(id: string): Promise<PackageDashboard> {
  return apiGet<PackageDashboard>(`/v1/bid-management/bid-packages/${id}/dashboard`);
}

/* ── Bidders ───────────────────────────────────────────────────────────── */

export function createBidder(data: CreateBidderPayload): Promise<Bidder> {
  return apiPost<Bidder>('/v1/bid-management/bidders/', data);
}

export function updateBidder(
  id: string,
  data: Partial<CreateBidderPayload>,
): Promise<Bidder> {
  return apiPatch<Bidder>(`/v1/bid-management/bidders/${id}`, data);
}

export function deleteBidder(id: string): Promise<void> {
  return apiDelete(`/v1/bid-management/bidders/${id}`);
}

export function disqualifyBidder(id: string, reason: string): Promise<Bidder> {
  return apiPost<Bidder>(`/v1/bid-management/bidders/${id}/disqualify`, { reason });
}

/* ── Invitations ───────────────────────────────────────────────────────── */

export function createInvitation(data: CreateInvitationPayload): Promise<BidInvitation> {
  return apiPost<BidInvitation>('/v1/bid-management/invitations/', data);
}

export function resendInvitation(id: string): Promise<BidInvitation> {
  return apiPost<BidInvitation>(`/v1/bid-management/invitations/${id}/resend`, {});
}

export function markInvitationOpened(id: string): Promise<BidInvitation> {
  return apiPost<BidInvitation>(`/v1/bid-management/invitations/${id}/mark-opened`, {});
}

export function declineInvitation(id: string, reason = ''): Promise<BidInvitation> {
  const qs = reason ? `?reason=${encodeURIComponent(reason)}` : '';
  return apiPost<BidInvitation>(
    `/v1/bid-management/invitations/${id}/decline${qs}`,
    {},
  );
}

/* ── Submissions ───────────────────────────────────────────────────────── */

export function createSubmission(data: {
  invitation_id: string;
  bidder_id: string;
  total_amount?: number | string;
  currency?: string;
  notes_to_owner?: string;
}): Promise<BidSubmission> {
  return apiPost<BidSubmission>('/v1/bid-management/submissions/', data);
}

export function withdrawSubmission(id: string): Promise<BidSubmission> {
  return apiPost<BidSubmission>(`/v1/bid-management/submissions/${id}/withdraw`, {});
}

/* ── Submission lines (priced) ─────────────────────────────────────────── */

export interface CreateSubmissionLinePayload {
  submission_id: string;
  line_item_id: string;
  unit_price?: number | string;
  quantity_priced?: number | string;
  inclusion_status?: string;
  comment?: string;
}

export function listSubmissionLines(submissionId: string): Promise<BidSubmissionLine[]> {
  return apiGet<BidSubmissionLine[]>(
    `/v1/bid-management/submission-lines/?submission_id=${submissionId}`,
  );
}

export function createSubmissionLine(
  data: CreateSubmissionLinePayload,
): Promise<BidSubmissionLine> {
  return apiPost<BidSubmissionLine>('/v1/bid-management/submission-lines/', data);
}

export function bulkCreateSubmissionLines(
  submissionId: string,
  items: Omit<CreateSubmissionLinePayload, 'submission_id'>[],
): Promise<BidSubmissionLine[]> {
  return apiPost<BidSubmissionLine[]>(
    `/v1/bid-management/submissions/${submissionId}/lines/bulk`,
    { items: items.map((i) => ({ ...i, submission_id: submissionId })) },
  );
}

/* ── Q & A ─────────────────────────────────────────────────────────────── */

export function createQA(data: CreateQAPayload): Promise<BidQA> {
  return apiPost<BidQA>('/v1/bid-management/q-and-a/', data);
}

export function answerQA(id: string, data: AnswerQAPayload): Promise<BidQA> {
  return apiPost<BidQA>(`/v1/bid-management/q-and-a/${id}/answer`, data);
}

export function deleteQA(id: string): Promise<void> {
  return apiDelete(`/v1/bid-management/q-and-a/${id}`);
}

/* ── Comparisons / Leveling ────────────────────────────────────────────── */

export function createComparison(data: CreateComparisonPayload): Promise<BidComparison> {
  return apiPost<BidComparison>('/v1/bid-management/comparisons/', data);
}

/** Idempotent: returns the existing comparison or creates one. */
export function getOrCreateComparison(
  data: CreateComparisonPayload,
): Promise<BidComparison> {
  return apiPost<BidComparison>('/v1/bid-management/comparisons/get-or-create', data);
}

/** Returns the package's single comparison header, or null if none yet. */
export function getPackageComparison(packageId: string): Promise<BidComparison | null> {
  return apiGet<BidComparison | null>(
    `/v1/bid-management/bid-packages/${packageId}/comparison`,
  );
}

/** Server-side, valid-only, currency-safe line×bidder leveling matrix. */
export function levelingMatrix(packageId: string): Promise<LevelingMatrix> {
  return apiGet<LevelingMatrix>(
    `/v1/bid-management/bid-packages/${packageId}/leveling-matrix`,
  );
}

export function computeLeveling(comparisonId: string): Promise<BidLevelingRow[]> {
  return apiPost<BidLevelingRow[]>(
    `/v1/bid-management/comparisons/${comparisonId}/compute-leveling`,
    {},
  );
}

export function levelingTable(comparisonId: string): Promise<LevelingTable> {
  return apiGet<LevelingTable>(
    `/v1/bid-management/comparisons/${comparisonId}/leveling-table`,
  );
}
